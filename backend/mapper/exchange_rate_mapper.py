import sqlite3
from datetime import datetime, timedelta

from config import CHINA_TZ, SYSTEM_SETTINGS_DB_FILE
from utils.logger import get_logger

logger = get_logger("ExchangeRateMapper")


class ExchangeRateMapper:
    """汇率历史数据持久化 — 存入 system_settings.db 的 exchange_rate_history 表"""

    def __init__(self, db_file: str = SYSTEM_SETTINGS_DB_FILE):
        self.db_file = db_file
        self.init_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def init_table(self) -> None:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS exchange_rate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rate REAL NOT NULL,
                timestamp INTEGER NOT NULL,
                source TEXT DEFAULT '',
                provider TEXT DEFAULT '',
                data_updated_at INTEGER DEFAULT 0
            )""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_exchange_rate_ts "
                "ON exchange_rate_history(timestamp)"
            )
            self._migrate_new_columns(c)
            conn.commit()

    @staticmethod
    def _migrate_new_columns(cursor) -> None:
        existing = {
            row[1] for row in cursor.execute("PRAGMA table_info(exchange_rate_history)")
        }
        for col_name, col_def in [
            ("source", "TEXT DEFAULT ''"),
            ("provider", "TEXT DEFAULT ''"),
            ("data_updated_at", "INTEGER DEFAULT 0"),
        ]:
            if col_name not in existing:
                try:
                    cursor.execute(
                        f"ALTER TABLE exchange_rate_history ADD COLUMN {col_name} {col_def}"
                    )
                except sqlite3.OperationalError as e:
                    logger.warning(f"迁移 exchange_rate_history.{col_name} 列失败: {e}")

    def save_rate(
        self,
        rate: float,
        source: str = "",
        provider: str = "",
        data_updated_at: int = 0,
    ) -> None:
        ts = int(datetime.now(CHINA_TZ).timestamp())
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO exchange_rate_history (rate, timestamp, source, provider, data_updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (rate, ts, source, provider, data_updated_at),
            )
            conn.commit()

    def get_latest_rate(self) -> float | None:
        """获取数据库中最新的汇率记录，作为所有接口都失败时的兜底"""
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT rate FROM exchange_rate_history ORDER BY timestamp DESC LIMIT 1"
                )
                row = c.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"查询最新汇率失败：{e}")
            return None

    def get_record_count(self) -> int:
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM exchange_rate_history")
                return c.fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"查询汇率记录数失败：{e}")
            return 0

    def get_statistics(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        where_clause, where_params = self._time_filter(hours, start_date, end_date)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT MIN(rate), MAX(rate), AVG(rate), COUNT(*), SUM(rate * rate) "
                f"FROM exchange_rate_history WHERE {where_clause}",
                where_params,
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

    def get_trend(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        where_clause, where_params = self._time_filter(hours, start_date, end_date)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT rate FROM exchange_rate_history WHERE {where_clause} ORDER BY timestamp",
                where_params,
            )
            rates = [row[0] for row in c.fetchall()]
        if len(rates) < 2:
            return {"slope": 0, "direction": "stable"}
        n = len(rates)
        x_mean = n / 2
        y_mean = sum(rates) / n
        numerator = sum((i - x_mean) * (r - y_mean) for i, r in enumerate(rates))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        if slope > 0.005:
            direction = "up"
        elif slope < -0.005:
            direction = "down"
        else:
            direction = "stable"
        return {"slope": slope, "direction": direction}

    def get_chart_series(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[tuple[datetime, float]]:
        where_clause, where_params = self._time_filter(hours, start_date, end_date)
        bucket_sql = _resolve_bucket(hours or 24)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                f"SELECT {bucket_sql} AS bucket, AVG(rate) AS rate "
                f"FROM exchange_rate_history WHERE {where_clause} "
                "GROUP BY bucket ORDER BY bucket",
                where_params,
            )
            return [
                (datetime.fromtimestamp(r[0], tz=CHINA_TZ), round(r[1], 4))
                for r in c.fetchall()
            ]

    def get_recent_records(
        self, hours: float = 24, limit: int = 20
    ) -> list[tuple[datetime, float]]:
        cutoff = int((datetime.now(CHINA_TZ) - timedelta(hours=hours)).timestamp())
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT timestamp, rate FROM exchange_rate_history "
                "WHERE timestamp > ? ORDER BY timestamp",
                (cutoff,),
            )
            rows = [
                (datetime.fromtimestamp(r[0], tz=CHINA_TZ), r[1]) for r in c.fetchall()
            ]
        return rows[-limit:] if len(rows) > limit else rows

    def get_dashboard_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> dict:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM exchange_rate_history")
            total = c.fetchone()[0]

            where_clause, where_params = self._time_filter(hours, start_date, end_date)
            c.execute(
                f"SELECT MAX(rate), MIN(rate) FROM exchange_rate_history "
                f"WHERE {where_clause}",
                where_params,
            )
            range_row = c.fetchone()
            today_high = range_row[0] if range_row else None
            today_low = range_row[1] if range_row else None

            now = datetime.now(CHINA_TZ)
            c.execute(
                "SELECT rate, timestamp FROM exchange_rate_history "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            row = c.fetchone()
            latest_rate = row[0] if row else None
            latest_time = datetime.fromtimestamp(row[1], tz=CHINA_TZ) if row else None
            freshness = (
                int((now - latest_time).total_seconds()) if latest_time else None
            )

            return {
                "record_count": total,
                "latest_rate": latest_rate,
                "latest_time": latest_time,
                "today_high": today_high,
                "today_low": today_low,
                "data_freshness_seconds": freshness,
            }

    def _time_filter(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, tuple]:
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


def _resolve_bucket(hours: float) -> str:
    if hours <= 24:
        return "timestamp"
    if hours <= 168:
        return "(timestamp / 600) * 600"
    if hours <= 720:
        return "(timestamp / 3600) * 3600"
    if hours <= 2160:
        return "(timestamp / 14400) * 14400"
    return "(timestamp / 86400) * 86400"
