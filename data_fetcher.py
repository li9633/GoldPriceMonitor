import requests
import time
from datetime import datetime
from typing import Optional
from config import GOLD_PRICE_API_URL, SYMBOL_NAME_MAP, OUNCE_TO_GRAM, USD_TO_CNY_RATE, USD_TO_CNY_API_URL
from logger import get_logger
from bs4 import BeautifulSoup

logger = get_logger("DataFetcher")

_RATE_CACHE_DURATION = 300  # 缓存 5 分钟
_last_rate_cache = {
    'rate': None,
    'timestamp': 0
}

# 定义不同品种类型的字段索引映射，以便更精确地提取数据
# 如果未来发现不同品种的时间/日期索引不同，可以在此扩展
FIELD_INDEX_MAP = {
    'default': {
        'price': 0,
        'time': 6,
        'date': 12
    },
    # 如果发现 hf_ 开头的品种索引不同，可以单独配置
    # 'hf': {
    #     'price': 0,
    #     'time': 6,
    #     'date': 12
    # }
}

_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36'
}


def fetch_realtime_exchange_rate() -> float:
    global _last_rate_cache
    current_time = time.time()

    # 如果缓存有效，直接返回
    if _last_rate_cache['rate'] and (current_time - _last_rate_cache['timestamp']) < _RATE_CACHE_DURATION:
        return _last_rate_cache['rate']

    try:
        response = requests.get(
            USD_TO_CNY_API_URL, headers=_headers, timeout=10)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'lxml')
            rate_element = soup.find(class_='_midMarketRateAmount_6vwmy_138')

            if rate_element:
                text_content = rate_element.get_text(strip=True)
                if '=' in text_content:
                    parts = text_content.split('=')
                    if len(parts) > 1:
                        right_part = parts[1].strip()
                        import re
                        match = re.search(r'(\d+\.\d+)', right_part)
                        if match:
                            rate = float(match.group(1))
                            # 更新缓存
                            _last_rate_cache['rate'] = rate
                            _last_rate_cache['timestamp'] = current_time
                            logger.info(f"成功获取并缓存实时汇率: {rate}")
                            return rate
    except Exception as e:
        logger.error(f"获取实时汇率异常: {e}")

    # 失败或无缓存时返回默认值
    return USD_TO_CNY_RATE


def convert_london_gold_to_cny(usd_price: float, exchange_rate: float = None) -> float:
    """
    将伦敦金(美元/盎司)转换为人民币/克
    :param usd_price: 伦敦金美元价格
    :param exchange_rate: 美元兑人民币汇率，如果为None则自动获取实时汇率
    :return: 人民币/克价格
    """
    if exchange_rate is None:
        # 每次调用都尝试获取最新汇率，或者你可以缓存这个值以减少请求
        exchange_rate = fetch_realtime_exchange_rate()

    # 公式: (美元/盎司 * 汇率) / 31.1035 = 人民币/克
    cny_per_gram = (usd_price * exchange_rate) / OUNCE_TO_GRAM
    return round(cny_per_gram, 2)


def fetch_current_price(symbol: str) -> Optional[dict]:
    """
    获取指定品种的当前价格数据
    支持多种黄金品种: gds_AUTD (黄金延期), hf_GC (纽约黄金), hf_XAU (伦敦金)
    返回字典格式: {'symbol': str, 'price': float, 'time': str, 'date': str, 'name': str}
    """
    try:
        timestamp = int(time.time() * 1000)
        url = f"{GOLD_PRICE_API_URL}?t={timestamp}"
        response = requests.get(url, headers=_headers, timeout=10)
        response.encoding = 'utf-8'
        response.raise_for_status()

        data_lines = response.text.strip().split('\n')
        for line in data_lines:
            if f'var hq_str_{symbol}=' in line:
                # 提取引号内的数据部分
                parts = line.split('"')
                if len(parts) < 2:
                    logger.warning(f"[{datetime.now()}] 解析{symbol}数据失败: 格式错误")
                    continue

                data_str = parts[1]
                fields = data_str.split(',')

                # 获取该 symbol 对应的字段索引配置，默认为 default
                indices = FIELD_INDEX_MAP.get('default')

                # 基本校验：确保字段数量足够
                max_index_needed = max(indices.values())
                if len(fields) <= max_index_needed:
                    logger.warning(
                        f"[{datetime.now()}] 解析{symbol}数据失败: 字段数量不足 ({len(fields)})")
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
                    logger.error(f"[{datetime.now()}] 转换{symbol}数据字段失败: {e}")
                    continue

    except Exception as e:
        logger.error(f"[{datetime.now()}] 获取{symbol}价格网络请求失败: {e}")

    return None


def fetch_all_gold_prices(symbols: list = ['gds_AUTD', 'hf_GC', 'hf_XAU']) -> dict:
    """
    一次性获取多个黄金品种的价格
    :param symbols: 需要获取的品种列表
    :return: 字典，key为symbol，value为价格数据字典或None
    """
    results = {}
    for symbol in symbols:
        data = fetch_current_price(symbol)
        results[symbol] = data
        if data:
            logger.info(f"成功获取 {data['name']} ({symbol}): {data['price']}")
        else:
            logger.warning(f"未能获取 {symbol} 的价格数据")
    return results
