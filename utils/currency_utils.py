import re
import time

from bs4 import BeautifulSoup

from config import OUNCE_TO_GRAM, USD_TO_CNY_API_URL, USD_TO_CNY_RATE
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("CurrencyUtils")

_RATE_CACHE_DURATION = 300
_last_rate_cache = {
    'rate': None,
    'timestamp': 0
}


def fetch_realtime_exchange_rate() -> float:
    current_time = time.time()

    if _last_rate_cache['rate'] and (current_time - _last_rate_cache['timestamp']) < _RATE_CACHE_DURATION:
        return _last_rate_cache['rate']

    response = safe_get(USD_TO_CNY_API_URL, timeout=10)
    if response is None:
        return USD_TO_CNY_RATE

    try:
        soup = BeautifulSoup(response.text, 'lxml')
        rate_element = soup.find(class_='_midMarketRateAmount_6vwmy_138')
        if rate_element:
            text_content = rate_element.get_text(strip=True)
            if '=' in text_content:
                parts = text_content.split('=')
                if len(parts) > 1:
                    match = re.search(r'(\d+\.\d+)', parts[1].strip())
                    if match:
                        rate = float(match.group(1))
                        _last_rate_cache['rate'] = rate
                        _last_rate_cache['timestamp'] = current_time
                        logger.info(f"成功获取并缓存实时汇率: {rate}")
                        return rate
    except (ValueError, AttributeError) as e:
        logger.error(f"获取实时汇率异常: {e}")

    return USD_TO_CNY_RATE


def convert_london_gold_to_cny(usd_price: float, exchange_rate: float | None = None) -> float:
    if exchange_rate is None:
        exchange_rate = fetch_realtime_exchange_rate()
    cny_per_gram = (usd_price * exchange_rate) / OUNCE_TO_GRAM
    return round(cny_per_gram, 2)