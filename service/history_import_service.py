import sqlite3
from datetime import datetime, timezone

import requests

from config import DB_FILE, SYMBOL
from mapper.price_mapper import PriceMapper
from utils.logger import get_logger

logger = get_logger("HistoryImportService")


class HistoryImportService:
    def __init__(self, db_file: str = DB_FILE, symbol: str = SYMBOL):
        self.price_mapper = PriceMapper(db_file)
        self.symbol = symbol

    def fetch_historical_data(self, period: str = "60d") -> list[dict]:
        url = f"https://www.huilvbiao.com/api/gold?d={period}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"获取历史数据失败：{e}")
            return []

    def import_data(self, data_list: list[dict]) -> int:
        self.price_mapper.init_table()
        records = []
        for item in data_list:
            try:
                date_time = datetime.fromtimestamp(item['date_time'] / 1000, tz=timezone.utc)
                price = float(item['price'])
                records.append((self.symbol, price, date_time))
            except (ValueError, KeyError, TypeError) as e:
                logger.error(f"转换数据失败：{e}")
                continue
        return self.price_mapper.batch_insert_prices(records)

    def import_all_historical_data(self) -> dict[str, int]:
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
    importer = HistoryImportService()

    if not importer.price_mapper.table_exists():
        logger.info("数据库表不存在，开始创建并导入历史数据...")
        logger.info("=" * 50)
        try:
            results = importer.import_all_historical_data()
            total = sum(results.values())
            logger.info("=" * 50)
            logger.info(f"历史数据初始化完成，共新增 {total} 条记录")
            return total > 0
        except (requests.RequestException, sqlite3.Error, ValueError) as e:
            logger.error(f"历史数据导入失败：{e}")
            return False

    existing_count = importer.price_mapper.get_record_count(importer.symbol)
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
    except (requests.RequestException, sqlite3.Error, ValueError) as e:
            logger.error(f"历史数据导入失败：{e}")
            return False