import sqlite3
from typing import List, Optional, Dict
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
            'count': len(prices),
            'std': self._calculate_std(prices)
        }

    def _calculate_std(self, prices: List[float]) -> float:
        """计算标准差"""
        if len(prices) < 2:
            return 0
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        return variance ** 0.5

    def get_moving_average(self, symbol: str, periods: int) -> Optional[float]:
        """计算移动平均线"""
        conn = sqlite3.connect(DB_FILE)
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

    def get_price_trend(self, symbol: str, hours: float) -> Dict:
        """分析价格趋势（斜率）"""
        conn = sqlite3.connect(DB_FILE)
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

        # 简单线性回归计算斜率
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

    def get_percentile(self, symbol: str, hours: float, percentile: float) -> Optional[float]:
        """获取历史价格的分位数"""
        prices = self.get_prices_in_window(symbol, hours)
        if not prices:
            return None

        prices.sort()
        index = int(len(prices) * percentile / 100)
        return prices[index]
