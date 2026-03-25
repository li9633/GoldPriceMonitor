
import sqlite3
from typing import List
from config import DB_FILE


class HistoryManager:
    def __init__(self):
        self.init_db()

    def init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS prices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      symbol TEXT,
                      price REAL)''')
        conn.commit()
        conn.close()

    def save_price(self, symbol: str, price: float):
        """保存价格到数据库"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO prices (symbol, price) VALUES (?, ?)",
                  (symbol, price))
        conn.commit()
        conn.close()

    def get_prices_in_window(self, symbol: str, hours: float) -> List[float]:
        """获取指定时间窗口内的价格列表"""
        conn = sqlite3.connect(DB_FILE)
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
        """获取时间窗口内的价格统计信息"""
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return {}
        return {
            'min': min(prices),
            'max': max(prices),
            'avg': sum(prices) / len(prices),
            'count': len(prices)
        }
