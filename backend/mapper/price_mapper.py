import sqlite3
from datetime import datetime, timedelta

from config import CHINA_TZ, PRICE_HISTORY_DB_FILE
from utils.logger import get_logger

logger = get_logger("PriceMapper")


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
        cutoff = datetime.now(CHINA_TZ) - timedelta(hours=hours)
        return [p for t, p in zip(self._timestamps, self._all) if t >= cutoff]

    def prices_last_n(self, n: int) -> list[float]:
        return self._all[-n:] if len(self._all) >= n else self._all

    def trend(self, hours: float) -> dict:
        subset = [
            (t, p)
            for t, p in zip(self._timestamps, self._all)
            if t >= datetime.now(CHINA_TZ) - timedelta(hours=hours)
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
        return prices[int(len(prices) * pct / 100)]

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


class PriceMapper:
    def __init__(self, db_file: str = PRICE_HISTORY_DB_FILE):
        self.db_file = db_file
        self.init_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size = -8000")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

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
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS prices
                         (id INTEGER PRIMARY KEY,
                          timestamp INTEGER NOT NULL,
                          symbol TEXT,
                          price REAL)""")
            conn.commit()
            self._ensure_indexes(conn)

    def table_exists(self) -> bool:
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='prices'"
                )
                return c.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"检查表结构失败：{e}")
            return False

    def save_price(self, symbol: str, price: float):
        ts = int(datetime.now(CHINA_TZ).timestamp())
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                (symbol, price, ts),
            )
            conn.commit()

    def get_prices_in_window(self, symbol: str, hours: float) -> list[float]:
        cutoff = int((datetime.now(CHINA_TZ) - timedelta(hours=hours)).timestamp())
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff),
            )
            return [row[0] for row in c.fetchall()]

    def get_check_snapshot(self, symbol: str) -> PriceSnapshot | None:
        """一次查询获取所有检查所需数据"""
        now = datetime.now(CHINA_TZ)
        with self._get_connection() as conn:
            c = conn.cursor()
            cutoff_24h = int((now - timedelta(hours=24)).timestamp())
            c.execute(
                "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff_24h),
            )
            rows = c.fetchall()
            if not rows:
                return None
            prices_with_time = [
                (datetime.fromtimestamp(r[0], tz=CHINA_TZ), r[1]) for r in rows
            ]
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 48",
                (symbol,),
            )
            ma_prices = [row[0] for row in c.fetchall()]
            ma_prices.reverse()
            cutoff_90d = int((now - timedelta(days=90)).timestamp())
            c.execute(
                "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
                (symbol, cutoff_90d),
            )
            min_3m = c.fetchone()[0]
            cutoff_180d = int((now - timedelta(days=180)).timestamp())
            c.execute(
                "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
                (symbol, cutoff_180d),
            )
            min_6m = c.fetchone()[0]
            return PriceSnapshot(prices_with_time, ma_prices, min_3m, min_6m)

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
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, periods),
            )
            prices = [row[0] for row in c.fetchall()]
            if not prices:
                return None
            return sum(prices) / len(prices)

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
        with self._get_connection() as conn:
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
        index = int(len(prices) * percentile / 100)
        return prices[index]

    def get_price_series(
        self, symbol: str, hours: float
    ) -> list[tuple[datetime, float]]:
        """获取原始价格序列，用于最近记录等需要精确数据的场景"""
        cutoff = int((datetime.now(CHINA_TZ) - timedelta(hours=hours)).timestamp())
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
                (symbol, cutoff),
            )
            return [
                (datetime.fromtimestamp(r[0], tz=CHINA_TZ), r[1]) for r in c.fetchall()
            ]

    def get_chart_series(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[tuple[datetime, float]]:
        """获取聚合后的价格序列，按时间范围自动降采样，用于图表渲染"""
        where_clause, where_params = self._price_time_filter(
            int(hours) if hours else None, start_date, end_date
        )
        bucket_sql = _resolve_bucket(hours or 24)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT {bucket_sql} AS bucket, AVG(price) AS price "
                f"FROM prices WHERE symbol = ? AND {where_clause} "
                "GROUP BY bucket ORDER BY bucket",
                (symbol, *where_params),
            )
            return [
                (datetime.fromtimestamp(r[0], tz=CHINA_TZ), round(r[1], 2))
                for r in c.fetchall()
            ]

    def get_record_count(self, symbol: str) -> int:
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,))
                return c.fetchone()[0]
        except sqlite3.OperationalError:
            return 0
        except sqlite3.Error as e:
            logger.error(f"查询数据条数失败：{e}")
            return 0

    def _price_time_filter(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, tuple]:
        """构建价格表的时间筛选 WHERE 子句和参数
        优先级：hours > start_date/end_date > 默认今天
        使用原始时间戳比较，确保索引可用"""
        if hours is not None and hours > 0:
            cutoff = int((datetime.now(CHINA_TZ) - timedelta(hours=hours)).timestamp())
            return "timestamp > ?", (cutoff,)
        if start_date and end_date:
            start_ts = int(
                datetime.strptime(start_date, "%Y-%m-%d")
                .replace(hour=0, minute=0, second=0, tzinfo=CHINA_TZ)
                .timestamp()
            )
            end_ts = int(
                datetime.strptime(end_date, "%Y-%m-%d")
                .replace(hour=23, minute=59, second=59, tzinfo=CHINA_TZ)
                .timestamp()
            )
            return "timestamp BETWEEN ? AND ?", (start_ts, end_ts)
        if start_date:
            start_ts = int(
                datetime.strptime(start_date, "%Y-%m-%d")
                .replace(hour=0, minute=0, second=0, tzinfo=CHINA_TZ)
                .timestamp()
            )
            return "timestamp >= ?", (start_ts,)
        if end_date:
            end_ts = int(
                datetime.strptime(end_date, "%Y-%m-%d")
                .replace(hour=23, minute=59, second=59, tzinfo=CHINA_TZ)
                .timestamp()
            )
            return "timestamp <= ?", (end_ts,)
        today = datetime.now(CHINA_TZ)
        start_ts = int(today.replace(hour=0, minute=0, second=0).timestamp())
        end_ts = int(today.replace(hour=23, minute=59, second=59).timestamp())
        return "timestamp BETWEEN ? AND ?", (start_ts, end_ts)

    def get_dashboard_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> dict:
        """仪表盘数据：总记录数 + 范围内新增 + 各品种统计"""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT symbol, COUNT(*) as cnt FROM prices GROUP BY symbol ORDER BY cnt DESC"
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

            now = datetime.now(CHINA_TZ)
            symbol_data = []
            for symbol, count in rows:
                c.execute(
                    "SELECT price, timestamp FROM prices WHERE symbol=? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (symbol,),
                )
                row = c.fetchone()
                latest_time = (
                    datetime.fromtimestamp(row[1], tz=CHINA_TZ) if row else None
                )
                freshness = (
                    int((now - latest_time).total_seconds()) if latest_time else None
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
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON prices(symbol, timestamp)"
            )
            conn.commit()
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
                except sqlite3.Error as e:
                    logger.error(f"导入单条数据失败：{e}")
                    continue
            conn.commit()
            return count

    def checkpoint(self) -> None:
        """将 WAL 中所有已提交数据合并回主库，并删除 WAL/SHM 文件"""
        with self._get_connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 完成，数据库已完整保存")


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
