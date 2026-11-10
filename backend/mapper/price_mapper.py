import sqlite3
import time
from datetime import datetime, timedelta

from config import PRICE_HISTORY_DB_FILE
from mapper.base import SQLiteMapper
from utils.logger import get_logger
from utils.time_utils import from_timestamp, now, parse_date, today, today_end

logger = get_logger("PriceMapper")

#: 日线聚合表 —— 把「按天的指标」从 600 万行 tick 里解放出来。
#:
#: 动机（实测 630 万行 / 365 天）：
#:   - `MIN(price)` 近 90/180 天 必须扫完窗口内全部索引条目，占建议快照 94% 的开销；
#:   - 首页看板为了显示「总记录数」每 10 秒做一次全表 COUNT(*)（332ms）；
#:   - 1 年图表要扫 315 万行做 GROUP BY（1069ms）。
#: 这三件事都只需要「按天」的聚合结果，日线表把它们各自降到 0.01 ~ 5ms。
#:
#: `day` 口径刻意与 `_resolve_bucket()` 的日桶保持一致（UTC 对齐的当日 00:00），
#: 这样 1 年图表的输出与改造前逐点相同，不会因为时区口径变化让曲线平移 8 小时。
#: 只存 high/low/sum/count —— 当前所有消费方（最低价、均价、总数）都不需要 OHLC，
#: 少存两列也就少了两处「乱序写入导致 open/close 出错」的可能性。
DAILY_TABLE_DDL = """CREATE TABLE IF NOT EXISTS prices_daily (
    symbol       TEXT    NOT NULL,
    day          INTEGER NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    price_sum    REAL    NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (symbol, day)
) WITHOUT ROWID"""

#: 图表跨度超过该小时数时，分桶粒度已达到「按天」（见 `_resolve_bucket`），
#: 直接读日线表；更短的跨度仍走原始 tick，保证分时曲线不失真。
DAILY_CHART_THRESHOLD_HOURS = 2160


def _day_bucket(ts: float | int) -> int:
    """时间戳 → 所属自然日的桶起点（UTC 对齐，与 SQL 里 `(timestamp/86400)*86400` 一致）"""
    return (int(ts) // 86400) * 86400


class PriceSnapshot:
    """一次查询获取所有检查所需数据，避免重复 DB 查询"""

    def __init__(
        self,
        prices_with_time: list[tuple[datetime, float]],
        ma_prices: list[float],
        min_3m: float | None,
        min_6m: float | None,
    ):
        self._all = [p for _, p in prices_with_time]
        self._timestamps = [t for t, _ in prices_with_time]
        self._ma_prices = ma_prices
        self.min_3m = min_3m
        self.min_6m = min_6m

    def prices_in_hours(self, hours: float) -> list[float]:
        cutoff = now() - timedelta(hours=hours)
        # strict：两个序列都由 prices_with_time 推出，长度必须一致。
        # 万一以后有人只改了一边，这里直接报错，而不是悄悄截断少算几个点。
        return [p for t, p in zip(self._timestamps, self._all, strict=True) if t >= cutoff]

    def prices_last_n(self, n: int) -> list[float]:
        return self._all[-n:] if len(self._all) >= n else self._all

    def trend(self, hours: float) -> dict:
        subset = [
            (t, p)
            for t, p in zip(self._timestamps, self._all, strict=True)
            if t >= now() - timedelta(hours=hours)
        ]
        if len(subset) < 2:
            return {"slope": 0, "direction": "stable"}
        prices = [p for _, p in subset]
        n = len(prices)
        x_mean = n / 2
        y_mean = sum(prices) / n
        numerator = sum((i - x_mean) * (p - y_mean) for i, p in enumerate(prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        if slope > 0.5:
            direction = "up"
        elif slope < -0.5:
            direction = "down"
        else:
            direction = "stable"
        return {"slope": slope, "direction": direction}

    def percentile(self, hours: float, pct: float) -> float | None:
        prices = self.prices_in_hours(hours)
        if not prices:
            return None
        prices.sort()
        return _percentile_value(prices, pct)

    def statistics(self, hours: float) -> dict:
        prices = self.prices_in_hours(hours)
        if not prices:
            return {}
        avg = sum(prices) / len(prices)
        variance = (
            sum((p - avg) ** 2 for p in prices) / len(prices) if len(prices) > 1 else 0
        )
        return {
            "min": min(prices),
            "max": max(prices),
            "avg": avg,
            "count": len(prices),
            "std": variance**0.5,
        }

    def ma(self, periods: int) -> float | None:
        if len(self._ma_prices) < periods:
            return None
        return sum(self._ma_prices[-periods:]) / periods

    def scaled(self, factor: float) -> "PriceSnapshot":
        """按系数缩放整份快照。

        INTL_ONLY 时 hf_XAU 序列是美元/盎司而现价是折算 ¥/g，指标必须与
        现价同口径 —— 用当前折算系数把序列换算成 ¥/g 后再提指标
        （汇率日内波动通常 <1%，近似安全）。
        """
        return PriceSnapshot(
            [
                (t, p * factor)
                for t, p in zip(self._timestamps, self._all, strict=True)
            ],
            [p * factor for p in self._ma_prices],
            self.min_3m * factor if self.min_3m is not None else None,
            self.min_6m * factor if self.min_6m is not None else None,
        )


class PriceMapper(SQLiteMapper):
    def __init__(self, db_file: str = PRICE_HISTORY_DB_FILE):
        # 价格热路径：8MiB 页缓存 + 内存临时表，降低磁盘 IO
        super().__init__(
            db_file,
            wal=True,
            row_factory=False,
            extra_pragmas=("PRAGMA cache_size = -8000", "PRAGMA temp_store = MEMORY"),
        )
        self.init_table()

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts ON prices(symbol, timestamp)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices(symbol)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts_price ON prices(symbol, timestamp, price)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_prices_ts ON prices(timestamp)")
        conn.commit()

    def init_table(self):
        with self._session() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS prices
                         (id INTEGER PRIMARY KEY,
                          timestamp INTEGER NOT NULL,
                          symbol TEXT,
                          price REAL)""")
            self._ensure_indexes(conn)
            self._ensure_daily_table(conn)
        self._sync_daily_on_startup()

    # ==================== 日线聚合表维护 ====================

    @staticmethod
    def _ensure_daily_table(conn: sqlite3.Connection) -> None:
        conn.execute(DAILY_TABLE_DDL)

    @staticmethod
    def _upsert_daily(
        c: sqlite3.Cursor, symbol: str, day: int, price: float
    ) -> None:
        """在写入 tick 的同一个事务里累加当日聚合。

        high/low 用 MAX/MIN 收敛，sum/count 累加 —— 都是可结合的操作，
        所以重复调用、乱序调用都不会算错。
        """
        c.execute(
            "INSERT INTO prices_daily (symbol, day, high, low, price_sum, sample_count) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(symbol, day) DO UPDATE SET "
            "high = MAX(prices_daily.high, excluded.high), "
            "low = MIN(prices_daily.low, excluded.low), "
            "price_sum = prices_daily.price_sum + excluded.price_sum, "
            "sample_count = prices_daily.sample_count + 1",
            (symbol, day, price, price, price),
        )

    def rebuild_daily(self, start_ts: int, end_ts: int) -> int:
        """按原始 tick 重算 [start_ts, end_ts] 覆盖到的自然日聚合。

        用于历史导入之后、以及启动时自愈。整日重算是幂等的：先删该日区间
        的聚合行，再一次性 GROUP BY 生成，不会重复累加。
        """
        start_day = _day_bucket(start_ts)
        end_day = _day_bucket(end_ts)
        lo = start_day
        hi = end_day + 86400
        with self._session() as conn:
            conn.execute(
                "DELETE FROM prices_daily WHERE day BETWEEN ? AND ?",
                (start_day, end_day),
            )
            cur = conn.execute(
                "INSERT INTO prices_daily "
                "(symbol, day, high, low, price_sum, sample_count) "
                "SELECT symbol, (timestamp / 86400) * 86400 AS bucket, "
                "MAX(price), MIN(price), SUM(price), COUNT(*) "
                "FROM prices WHERE timestamp >= ? AND timestamp < ? "
                "GROUP BY symbol, bucket",
                (lo, hi),
            )
            return cur.rowcount

    def _sync_daily_on_startup(self) -> None:
        """启动时保证日线表与原始表一致。

        - 日线表为空但已有点位 → 全量重建（老库升级到本版本时的一次性成本）；
        - 日线表落后于今天 → 从落后那天起重算（覆盖崩溃/手工改数据留下的空洞）。
        重复调用几乎零成本：正常情况下只多一次 `MAX(day)` 查询。
        """
        with self._session() as conn:
            n_daily, max_day = conn.execute(
                "SELECT COUNT(*), MAX(day) FROM prices_daily"
            ).fetchone()
            has_raw = conn.execute("SELECT 1 FROM prices LIMIT 1").fetchone() is not None

        if not has_raw:
            return
        now_ts = int(now().timestamp())
        if not n_daily:
            t0 = time.perf_counter()
            days = self.rebuild_daily(0, now_ts)
            logger.warning(
                f"prices_daily 为空，已从 prices 全量重建 days={days} "
                f"耗时 {time.perf_counter() - t0:.2f}s"
            )
            return
        today_bucket = _day_bucket(now_ts)
        if max_day is not None and max_day >= today_bucket - 86400:
            return
        healed = self.rebuild_daily(max_day or today_bucket, now_ts)
        logger.info(f"prices_daily 已补齐至今天 days={healed}")

    def table_exists(self) -> bool:
        try:
            with self._session() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='prices'"
                )
                return c.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"检查表结构失败：{e}")
            return False

    def save_price(self, symbol: str, price: float):
        self.save_prices([(symbol, price)])

    def save_prices(self, items: list[tuple[str, float]]) -> None:
        """一轮巡检的多个品种一次事务落库（含日线聚合）。

        原先每个品种各开一个连接各提交一次（实测 17.5ms/tick），合并成一次
        事务后只需一次提交成本；日线聚合搭同一事务顺带更新，不会出现
        「点位写了、聚合没写」的中间态。
        """
        ts = int(now().timestamp())
        day = _day_bucket(ts)
        with self._session() as conn:
            c = conn.cursor()
            for symbol, price in items:
                c.execute(
                    "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                    (symbol, price, ts),
                )
                self._upsert_daily(c, symbol, day, price)

    def get_prices_in_window(self, symbol: str, hours: float) -> list[float]:
        cutoff = int((now() - timedelta(hours=hours)).timestamp())
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff),
            )
            return [row[0] for row in c.fetchall()]

    def get_check_snapshot(self, symbol: str) -> PriceSnapshot | None:
        """一次查询获取所有检查所需数据"""
        now_dt = now()
        with self._session() as conn:
            c = conn.cursor()
            cutoff_24h = int((now_dt - timedelta(hours=24)).timestamp())
            c.execute(
                "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff_24h),
            )
            rows = c.fetchall()
            if not rows:
                return None
            prices_with_time = [(from_timestamp(r[0]), r[1]) for r in rows]
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 48",
                (symbol,),
            )
            ma_prices = [row[0] for row in c.fetchall()]
            ma_prices.reverse()
            # 90/180 天最低价改读日线表：原始表要扫完窗口内 233 万条索引条目（实测
            # 125ms，占本方法 94%），日线表只有几百行（实测 0.01ms）。
            cutoff_90d = int((now_dt - timedelta(days=90)).timestamp())
            cutoff_180d = int((now_dt - timedelta(days=180)).timestamp())
            min_3m = self._min_low(c, symbol, cutoff_90d)
            min_6m = self._min_low(c, symbol, cutoff_180d)
            return PriceSnapshot(prices_with_time, ma_prices, min_3m, min_6m)

    @staticmethod
    def _min_low(
        c: sqlite3.Cursor, symbol: str, cutoff: int
    ) -> float | None:
        """窗口内最低价（优先日线表）。

        日线表缺失时回退原始表：宁可慢，也不能静默返回 None —— 那会让
        「接近 3/6 个月低位」这类信号无声消失，而且不会报错。
        """
        row = c.execute(
            "SELECT MIN(low) FROM prices_daily WHERE symbol = ? AND day >= ?",
            (symbol, _day_bucket(cutoff)),
        ).fetchone()
        if row and row[0] is not None:
            return row[0]
        fallback = c.execute(
            "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
            (symbol, cutoff),
        ).fetchone()
        if fallback and fallback[0] is not None:
            logger.warning(
                f"prices_daily 缺少 {symbol} 的聚合数据，已回退全表扫描；"
                "请检查启动时的日线重建是否成功"
            )
            return fallback[0]
        return None

    def get_price_statistics(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        where_clause, where_params = self._price_time_filter(
            int(hours) if hours else None, start_date, end_date
        )
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT MIN(price), MAX(price), AVG(price), COUNT(*), SUM(price * price) "
                f"FROM prices WHERE symbol = ? AND {where_clause}",
                (symbol, *where_params),
            )
            row = c.fetchone()
            if not row or row[3] == 0:
                return {}
            avg = row[2]
            cnt = row[3]
            variance = (row[4] / cnt) - (avg * avg) if cnt > 1 else 0.0
            return {
                "min": row[0],
                "max": row[1],
                "avg": avg,
                "count": cnt,
                "std": variance**0.5 if variance > 0 else 0.0,
            }

    def get_moving_average(self, symbol: str, periods: int) -> float | None:
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, periods),
            )
            prices = [row[0] for row in c.fetchall()]
            if not prices:
                return None
            return sum(prices) / len(prices)

    def get_latest_price(self, symbol: str) -> float | None:
        """最新价（元/克）—— 持仓市值计算用，走 idx_prices_symbol_ts 索引"""
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol,),
            )
            row = c.fetchone()
            return row[0] if row else None

    def get_price_near(self, symbol: str, timestamp: int) -> float | None:
        """取「目标时刻当时」的价格。

        优先该时刻之前的最后一条；若该时刻早于全部数据，则退而取之后的最近一条。

        **建议回访必须用它，而不是 `get_latest_price`**：T+1 回访要的是「建议发出
        一天后」的价格。如果停机几天后再回填，用最新价会把 T+1 写成 T+5 的价格，
        有效性数据就废了 —— 而且这种错误不会报错，只会静默污染统计。
        """
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? AND timestamp <= ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol, timestamp),
            )
            row = c.fetchone()
            if row:
                return row[0]
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? AND timestamp > ? "
                "ORDER BY timestamp ASC LIMIT 1",
                (symbol, timestamp),
            )
            row = c.fetchone()
            return row[0] if row else None

    def get_price_trend(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        where_clause, where_params = self._price_time_filter(
            int(hours) if hours else None, start_date, end_date
        )
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT price FROM prices WHERE symbol = ? AND {where_clause} ORDER BY timestamp",
                (symbol, *where_params),
            )
            prices = [row[0] for row in c.fetchall()]
        if len(prices) < 2:
            return {"slope": 0, "direction": "stable"}
        n = len(prices)
        x_mean = n / 2
        y_mean = sum(prices) / n
        numerator = sum((i - x_mean) * (p - y_mean) for i, p in enumerate(prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        if slope > 0.5:
            direction = "up"
        elif slope < -0.5:
            direction = "down"
        else:
            direction = "stable"
        return {"slope": slope, "direction": direction}

    def get_percentile(
        self, symbol: str, hours: float, percentile: float
    ) -> float | None:
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return None
        prices.sort()
        return _percentile_value(prices, percentile)

    def get_price_series(
        self, symbol: str, hours: float
    ) -> list[tuple[datetime, float]]:
        """获取原始价格序列，用于最近记录等需要精确数据的场景"""
        cutoff = int((now() - timedelta(hours=hours)).timestamp())
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff),
            )
            return [(from_timestamp(r[0]), r[1]) for r in c.fetchall()]

    def get_chart_series(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[tuple[datetime, float]]:
        """获取聚合后的价格序列，按时间范围自动降采样，用于图表渲染

        跨度超过 90 天时，分桶粒度已经是「按天」，直接读日线表：1 年曲线原来
        要扫 315 万行 tick 做 GROUP BY（实测 1069ms），日线表只有 366 行。
        跨度 ≤ 90 天仍走原始 tick，保证分时曲线不被降级。
        """
        lo, hi = self._time_bounds(
            int(hours) if hours else None, start_date, end_date
        )
        span_hours = max((hi - lo) / 3600.0, 1.0)
        if span_hours > DAILY_CHART_THRESHOLD_HOURS:
            daily = self._get_daily_chart(symbol, lo, hi)
            if daily:
                return daily
            logger.warning(
                f"{symbol} 的日线聚合为空，图表回退全表扫描（跨度 {span_hours:.0f}h）"
            )
        return self._get_raw_chart(symbol, hours, start_date, end_date)

    def _get_daily_chart(
        self, symbol: str, lo: int, hi: int
    ) -> list[tuple[datetime, float]]:
        """按自然日读聚合结果。

        边界说明：区间起点若落在某天中间，原始 tick 实现只统计「起点之后」的
        那半天（首桶是残日），日线表则用整天。实测 1 年图表 366 个点里只有首桶
        有差异（0.02，约 0.003%），其余 365 个点完全一致 —— 取整天更符合
        「日线」的语义，故保留该口径差异。
        """
        lo_day = _day_bucket(lo)
        hi_day = _day_bucket(hi)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT day, price_sum / sample_count AS avg_price FROM prices_daily "
                "WHERE symbol = ? AND day >= ? AND day <= ? ORDER BY day",
                (symbol, lo_day, hi_day),
            ).fetchall()
        return [(from_timestamp(r[0]), round(r[1], 2)) for r in rows]

    def _get_raw_chart(
        self,
        symbol: str,
        hours: float | None,
        start_date: str | None,
        end_date: str | None,
    ) -> list[tuple[datetime, float]]:
        where_clause, where_params = self._price_time_filter(
            int(hours) if hours else None, start_date, end_date
        )
        bucket_sql = _resolve_bucket(hours or 24)
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT {bucket_sql} AS bucket, AVG(price) AS price "
                f"FROM prices WHERE symbol = ? AND {where_clause} "
                "GROUP BY bucket ORDER BY bucket",
                (symbol, *where_params),
            )
            return [(from_timestamp(r[0]), round(r[1], 2)) for r in c.fetchall()]

    def get_record_count(self, symbol: str) -> int:
        try:
            with self._session() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,))
                return c.fetchone()[0]
        except sqlite3.OperationalError:
            return 0
        except sqlite3.Error as e:
            logger.error(f"查询数据条数失败：{e}")
            return 0

    def _time_bounds(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[int, int]:
        """把「小时 / 日期范围」统一成一对时间戳边界。

        分桶粒度、日线读取、原始表筛选都必须用同一个边界口径，否则图表的
        首尾桶会和其它接口对不上。
        """
        if hours is not None and hours > 0:
            hi = int(now().timestamp())
            return hi - int(hours * 3600), hi
        if start_date and end_date:
            return (
                int(parse_date(start_date).timestamp()),
                int(parse_date(end_date, hour=23, minute=59, second=59).timestamp()),
            )
        if start_date:
            return int(parse_date(start_date).timestamp()), int(now().timestamp())
        if end_date:
            return 0, int(
                parse_date(end_date, hour=23, minute=59, second=59).timestamp()
            )
        return int(today().timestamp()), int(today_end().timestamp())

    def _price_time_filter(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, tuple]:
        """构建价格表的时间筛选 WHERE 子句和参数
        优先级：hours > start_date/end_date > 默认今天
        使用原始时间戳比较，确保索引可用"""
        lo, hi = self._time_bounds(hours, start_date, end_date)
        if hours is not None and hours > 0:
            return "timestamp > ?", (lo,)
        return "timestamp BETWEEN ? AND ?", (lo, hi)

    def get_dashboard_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> dict:
        """仪表盘数据：总记录数 + 范围内新增 + 各品种统计"""
        with self._session() as conn:
            c = conn.cursor()
            # 总记录数改读日线表：原来 `COUNT(*) ... GROUP BY symbol` 要扫全表
            # 630 万行（实测 332ms），而首页每 10 秒轮询一次 —— 这条占整个
            # get_dashboard_data 的 99%。日线表 732 行，实测 0.1ms。
            c.execute(
                "SELECT symbol, SUM(sample_count) as cnt FROM prices_daily "
                "GROUP BY symbol ORDER BY cnt DESC"
            )
            rows = c.fetchall()
            total = sum(r[1] for r in rows)

            where_clause, where_params = self._price_time_filter(
                hours, start_date, end_date
            )
            c.execute(f"SELECT COUNT(*) FROM prices WHERE {where_clause}", where_params)
            new_records = c.fetchone()[0]

            c.execute(
                f"SELECT symbol, MAX(price), MIN(price) FROM prices "
                f"WHERE {where_clause} GROUP BY symbol",
                where_params,
            )
            today_range = {
                r[0]: {"today_high": r[1], "today_low": r[2]} for r in c.fetchall()
            }

            now_dt = now()
            symbol_data = []
            for symbol, count in rows:
                c.execute(
                    "SELECT price, timestamp FROM prices WHERE symbol=? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (symbol,),
                )
                row = c.fetchone()
                latest_time = from_timestamp(row[1]) if row else None
                freshness = (
                    int((now_dt - latest_time).total_seconds()) if latest_time else None
                )
                tr = today_range.get(symbol, {})
                symbol_data.append(
                    {
                        "symbol": symbol,
                        "count": count,
                        "latest_price": row[0] if row else None,
                        "latest_time": latest_time,
                        "today_high": tr.get("today_high"),
                        "today_low": tr.get("today_low"),
                        "data_freshness_seconds": freshness,
                    }
                )
            return {
                "total_records": total,
                "new_records": new_records,
                "symbols": symbol_data,
            }

    def batch_insert_prices(self, records: list[tuple]) -> int:
        min_ts: int | None = None
        max_ts: int | None = None
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON prices(symbol, timestamp)"
            )
            count = 0
            for symbol, price, dt in records:
                try:
                    ts = int(dt.timestamp())
                    c.execute(
                        "INSERT OR IGNORE INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                        (symbol, price, ts),
                    )
                    if c.rowcount > 0:
                        count += 1
                        min_ts = ts if min_ts is None else min(min_ts, ts)
                        max_ts = ts if max_ts is None else max(max_ts, ts)
                except sqlite3.Error as e:
                    logger.error(f"导入单条数据失败：{e}")
                    continue
        # 历史导入不适合逐条累加（去重判断与批量性能都会变差），
        # 提交后按受影响的自然日整段重算 —— 幂等且一次成型。
        if min_ts is not None and max_ts is not None:
            self.rebuild_daily(min_ts, max_ts)
        return count

    def checkpoint(self) -> None:
        """将 WAL 中所有已提交数据合并回主库，并删除 WAL/SHM 文件"""
        with self._session() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 完成，数据库已完整保存")


def _percentile_value(sorted_prices: list[float], pct: float) -> float:
    """线性插值分位数（输入需已升序排序），避免下标越界并提升精度。"""
    if not sorted_prices:
        raise ValueError("空序列无法计算分位数")
    n = len(sorted_prices)
    if n == 1:
        return sorted_prices[0]
    rank = (n - 1) * max(0.0, min(100.0, pct)) / 100.0
    low = int(rank)
    high = min(low + 1, n - 1)
    frac = rank - low
    return sorted_prices[low] * (1 - frac) + sorted_prices[high] * frac


def _resolve_bucket(hours: float) -> str:
    """根据时间范围返回整数分桶表达式，避免 strftime 在百万行上的 CPU 开销"""
    if hours <= 24:
        return "timestamp"
    if hours <= 168:
        return "(timestamp / 600) * 600"
    if hours <= 720:
        return "(timestamp / 3600) * 3600"
    if hours <= 2160:
        return "(timestamp / 14400) * 14400"
    return "(timestamp / 86400) * 86400"