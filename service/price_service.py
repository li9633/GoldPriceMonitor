import time
from datetime import datetime, timedelta, timezone

import requests

from config import GOLD_PRICE_API_URL, SYMBOL_NAME_MAP
from utils.currency_utils import convert_london_gold_to_cny
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("PriceService")

FIELD_INDEX_MAP = {
    'default': {
        'price': 0,
        'time': 6,
        'date': 12
    }
}


class PriceService:
    def __init__(self):
        self.api_url = GOLD_PRICE_API_URL

    def fetch_current_price(self, symbol: str) -> dict | None:
        try:
            timestamp = int(time.time() * 1000)
            url = f"{self.api_url}?t={timestamp}"
            response = safe_get(url, timeout=10)
            if response is None:
                return None

            data_lines = response.text.strip().split('\n')
            for line in data_lines:
                if f'var hq_str_{symbol}=' in line:
                    parts = line.split('"')
                    if len(parts) < 2:
                        logger.warning(f"[{datetime.now(timezone(timedelta(hours=8)))}] 解析{symbol}数据格式错误")
                        continue

                    data_str = parts[1]
                    fields = data_str.split(',')
                    indices = FIELD_INDEX_MAP.get('default')

                    max_index_needed = max(indices.values())
                    if len(fields) <= max_index_needed:
                        logger.warning(
                            f"[{datetime.now(timezone(timedelta(hours=8)))}] 解析{symbol}数据字段不足 ({len(fields)})")
                        continue

                    try:
                        price = float(fields[indices['price']])
                        trade_time = fields[indices['time']]
                        trade_date = fields[indices['date']]
                        name = SYMBOL_NAME_MAP.get(symbol, symbol)

                        return {
                            'symbol': symbol,
                            'price': price,
                            'time': trade_time,
                            'date': trade_date,
                            'name': name
                        }
                    except (ValueError, IndexError) as e:
                        logger.error(
                            f"[{datetime.now(timezone(timedelta(hours=8)))}] 转换{symbol}数据字段失败: {e}")
                        continue

        except requests.RequestException as e:
            logger.error(f"[{datetime.now(timezone(timedelta(hours=8)))}] 获取{symbol}价格网络请求失败: {e}")

        return None

    def fetch_all_gold_prices(self, symbols: list[str]) -> dict[str, dict | None]:
        results = {}
        for symbol in symbols:
            data = self.fetch_current_price(symbol)
            if data and 'hf_XAU' == symbol:
                data['converted_cny_price'] = convert_london_gold_to_cny(
                    data['price'], None)
            results[symbol] = data
            if data:
                logger.info(f"成功获取 {data['name']} ({symbol}): {data['price']}")
            else:
                logger.warning(f"未能获取 {symbol} 的价格数据")
        return results