import sqlite3
from datetime import datetime, timedelta, timezone

from config import DB_FILE
from utils.logger import get_logger

logger = get_logger("PriceMapper")


class PriceMapper:
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        return conn

    def init_table(self):
        conn = self._get_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS prices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      symbol TEXT,
                      price REAL)''')
        conn.commit()
        conn.close()

    def table_exists(self) -> bool:
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prices'")
            exists = c.fetchone() is not None
            conn.close()
            return exists
        except sqlite3.Error as e:
            logger.error(f"检查表结构失败：{e}")
            return False

    def save_price(self, symbol: str, price: float):
        conn = self._get_connection()
        current_time = datetime.now(timezone(timedelta(hours=8)))
        c = conn.cursor()
        c.execute("INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                  (symbol, price, current_time))
        conn.commit()
        conn.close()

    def get_prices_in_window(self, symbol: str, hours: float) -> list[float]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""SELECT price FROM prices 
                     WHERE symbol = ? 
                     AND timestamp > datetime('now', ?)
                     ORDER BY timestamp""",
                  (symbol, f'-{hours} hours'))
        prices = [row[0] for row in c.fetchall()]
        conn.close()
        return prices

    def get_price_statistics(self, symbol: str, hours: float) -> dict:
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return {}
        return {
            'min': min(prices),
            'max': max(prices),
            'avg': sum(prices) / len(prices),
            'count': len(prices),
            'std': self._calculate_std(prices)
        }

    def _calculate_std(self, prices: list[float]) -> float:
        if len(prices) < 2:
            return 0
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        return variance ** 0.5

    def get_moving_average(self, symbol: str, periods: int) -> float | None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""SELECT price FROM prices 
                     WHERE symbol = ? 
                     ORDER BY timestamp DESC LIMIT ?""",
                  (symbol, periods))
        prices = [row[0] for row in c.fetchall()]
        conn.close()
        if not prices:
            return None
        return sum(prices) / len(prices)

    def get_price_trend(self, symbol: str, hours: float) -> dict:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""SELECT timestamp, price FROM prices 
                     WHERE symbol = ? 
                     AND timestamp > datetime('now', ?)
                     ORDER BY timestamp""",
                  (symbol, f'-{hours} hours'))
        data = c.fetchall()
        conn.close()

        if len(data) < 2:
            return {'slope': 0, 'direction': 'stable'}

        n = len(data)
        prices = [row[1] for row in data]
        x_mean = n / 2
        y_mean = sum(prices) / n

        numerator = sum((i - x_mean) * (p - y_mean)
                        for i, p in enumerate(prices))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0

        if slope > 0.5:
            direction = 'up'
        elif slope < -0.5:
            direction = 'down'
        else:
            direction = 'stable'

        return {'slope': slope, 'direction': direction}

    def get_percentile(self, symbol: str, hours: float, percentile: float) -> float | None:
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return None
        prices.sort()
        index = int(len(prices) * percentile / 100)
        return prices[index]

    def get_record_count(self, symbol: str) -> int:
        try:
            conn = self._get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?", (symbol,))
            count = c.fetchone()[0]
            conn.close()
            return count
        except sqlite3.OperationalError:
            return 0
        except sqlite3.Error as e:
            logger.error(f"查询数据条数失败：{e}")
            return 0

    def record_exists(self, symbol: str, timestamp: datetime) -> bool:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ? AND timestamp = ?",
                  (symbol, timestamp))
        exists = c.fetchone()[0] > 0
        conn.close()
        return exists

    def batch_insert_prices(self, records: list[tuple]) -> int:
        count = 0
        conn = self._get_connection()
        c = conn.cursor()
        for symbol, price, timestamp in records:
            try:
                if not self.record_exists(symbol, timestamp):
                    c.execute("INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                              (symbol, price, timestamp))
                    count += 1
            except sqlite3.Error as e:
                logger.error(f"导入单条数据失败：{e}")
                continue
        conn.commit()
        conn.close()
        return count