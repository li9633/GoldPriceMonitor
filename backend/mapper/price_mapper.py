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

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts ON prices(symbol, timestamp)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices(symbol)")
        conn.commit()

    def close(self):
        pass

    def init_table(self):
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS prices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      symbol TEXT,
                      price REAL)""")
        conn.commit()
        self._ensure_indexes(conn)

    def table_exists(self) -> bool:
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prices'"
            )
            exists = c.fetchone() is not None
            return exists
        except sqlite3.Error as e:
            logger.error(f"检查表结构失败：{e}")
            return False

    def save_price(self, symbol: str, price: float):
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
            (symbol, price, datetime.now(CHINA_TZ)),
        )
        conn.commit()

    def get_prices_in_window(self, symbol: str, hours: float) -> list[float]:
        cutoff = datetime.now(CHINA_TZ) - timedelta(hours=hours)
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
            (symbol, cutoff),
        )
        prices = [row[0] for row in c.fetchall()]
        return prices

    def get_check_snapshot(self, symbol: str) -> PriceSnapshot | None:
        """一次查询获取所有检查所需数据"""
        conn = self._get_connection()
        c = conn.cursor()
        cutoff_24h = datetime.now(CHINA_TZ) - timedelta(hours=24)
        c.execute(
            "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
            (symbol, cutoff_24h),
        )
        rows = c.fetchall()
        if not rows:
            return None
        prices_with_time = [
            (datetime.fromisoformat(r[0]).replace(tzinfo=CHINA_TZ), r[1]) for r in rows
        ]
        c.execute(
            "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 48",
            (symbol,),
        )
        ma_prices = [row[0] for row in c.fetchall()]
        ma_prices.reverse()
        c.execute(
            "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
            (symbol, datetime.now(CHINA_TZ) - timedelta(days=90)),
        )
        min_3m = c.fetchone()[0]
        c.execute(
            "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
            (symbol, datetime.now(CHINA_TZ) - timedelta(days=180)),
        )
        min_6m = c.fetchone()[0]
        return PriceSnapshot(prices_with_time, ma_prices, min_3m, min_6m)

    def get_price_statistics(self, symbol: str, hours: float) -> dict:
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return {}
        return {
            "min": min(prices),
            "max": max(prices),
            "avg": sum(prices) / len(prices),
            "count": len(prices),
            "std": self._calculate_std(prices),
        }

    def _calculate_std(self, prices: list[float]) -> float:
        if len(prices) < 2:
            return 0
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        return variance**0.5

    def get_moving_average(self, symbol: str, periods: int) -> float | None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
            (symbol, periods),
        )
        prices = [row[0] for row in c.fetchall()]
        if not prices:
            return None
        return sum(prices) / len(prices)

    def get_price_trend(self, symbol: str, hours: float) -> dict:
        cutoff = datetime.now(CHINA_TZ) - timedelta(hours=hours)
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
            (symbol, cutoff),
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
        """获取带时间戳的价格序列，用于图表渲染"""
        cutoff = datetime.now(CHINA_TZ) - timedelta(hours=hours)
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
            (symbol, cutoff),
        )
        return [
            (datetime.fromisoformat(r[0]).replace(tzinfo=CHINA_TZ), r[1])
            for r in c.fetchall()
        ]

    def get_record_count(self, symbol: str) -> int:
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,))
            count = c.fetchone()[0]
            return count
        except sqlite3.OperationalError:
            return 0
        except sqlite3.Error as e:
            logger.error(f"查询数据条数失败：{e}")
            return 0

    def batch_insert_prices(self, records: list[tuple]) -> int:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON prices(symbol, timestamp)"
        )
        conn.commit()
        count = 0
        for symbol, price, timestamp in records:
            try:
                c.execute(
                    "INSERT OR IGNORE INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                    (symbol, price, timestamp),
                )
                if c.rowcount > 0:
                    count += 1
            except sqlite3.Error as e:
                logger.error(f"导入单条数据失败：{e}")
                continue
        conn.commit()
        return count
