import requests
import sqlite3
from datetime import datetime
from typing import List, Dict
from config import DB_FILE, SYMBOL
from logger import get_logger
logger = get_logger("DataImporter")


class DataImporter:
    def __init__(self):
        self.db_file = DB_FILE
        self.symbol = SYMBOL

    def fetch_historical_data(self, period: str = "60d") -> List[Dict]:
        """从接口获取历史数据"""
        url = f"https://www.huilvbiao.com/api/gold?d={period}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取历史数据失败：{e}")
            return []

    def init_db(self):
        """确保数据库表结构正确"""
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS prices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      symbol TEXT,
                      price REAL)''')
        conn.commit()
        conn.close()

    def table_exists(self) -> bool:
        """检查 prices 表是否存在"""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='prices'
            """)
            exists = c.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.error(f"检查表结构失败：{e}")
            return False

    def get_existing_count(self) -> int:
        """获取数据库中已有数据条数"""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ?",
                      (self.symbol,))
            count = c.fetchone()[0]
            conn.close()
            return count
        except sqlite3.OperationalError:
            # 表不存在
            return 0
        except Exception as e:
            logger.error(f"查询数据条数失败：{e}")
            return 0

    def import_data(self, data_list: List[Dict]) -> int:
        """批量导入历史数据"""
        self.init_db()  # 确保表存在
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        count = 0
        for item in data_list:
            try:
                date_time = datetime.fromtimestamp(item['date_time'] / 1000)
                price = float(item['price'])

                c.execute("SELECT COUNT(*) FROM prices WHERE symbol = ? AND timestamp = ?",
                          (self.symbol, date_time))
                if c.fetchone()[0] == 0:
                    c.execute("INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                              (self.symbol, price, date_time))
                    count += 1
            except Exception as e:
                logger.error(f"导入单条数据失败：{e}")
                continue

        conn.commit()
        conn.close()
        return count

    def import_all_historical_data(self) -> Dict[str, int]:
        """导入所有历史数据"""
        results = {}

        logger.info("正在导入 60 天历史数据...")
        data_60d = self.fetch_historical_data(period="60d")
        if data_60d:
            count_60d = self.import_data(data_60d)
            results['60d'] = count_60d
            logger.info(f"60 天数据导入完成，新增 {count_60d} 条记录")
        else:
            results['60d'] = 0
            logger.error("60 天数据获取失败")

        logger.info("正在导入 1 年历史数据...")
        data_1y = self.fetch_historical_data(period="1y")
        if data_1y:
            count_1y = self.import_data(data_1y)
            results['1y'] = count_1y
            logger.info(f"1 年数据导入完成，新增 {count_1y} 条记录")
        else:
            results['1y'] = 0
            logger.error("1 年数据获取失败")

        return results


def init_historical_data() -> bool:
    """程序启动时初始化历史数据"""
    importer = DataImporter()

    # 检查表是否存在，不存在则直接导入
    if not importer.table_exists():
        logger.info("数据库表不存在，开始创建并导入历史数据...")
        logger.info("=" * 50)
        try:
            results = importer.import_all_historical_data()
            total = sum(results.values())
            logger.info("=" * 50)
            logger.info(f"历史数据初始化完成，共新增 {total} 条记录")
            return total > 0
        except Exception as e:
            logger.error(f"历史数据导入失败：{e}")
            return False

    # 表存在，检查数据量
    existing_count = importer.get_existing_count()
    if existing_count >= 100:
        logger.info(f"数据库已有 {existing_count} 条历史记录，跳过导入")
        return True

    logger.info(f"数据库仅有 {existing_count} 条记录，开始导入历史数据...")
    logger.info("=" * 50)

    try:
        results = importer.import_all_historical_data()
        total = sum(results.values())
        logger.info("=" * 50)
        logger.info(f"历史数据初始化完成，共新增 {total} 条记录")
        return total > 0
    except Exception as e:
        logger.error(f"历史数据导入失败：{e}")
        return False


if __name__ == "__main__":
    init_historical_data()
