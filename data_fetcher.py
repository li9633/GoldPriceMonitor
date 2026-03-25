# data_fetcher.py
import requests
import time
from datetime import datetime
from typing import Optional
from config import API_URL, SYMBOL_NAME_MAP


def fetch_current_price(symbol: str) -> Optional[dict]:
    """
    获取指定品种的当前价格数据
    返回字典格式: {'price': float, 'time': str, 'name': str}
    """
    try:
        timestamp = int(time.time() * 1000)
        url = f"{API_URL}?t={timestamp}"
        response = requests.get(url, timeout=10)
        response.encoding = 'utf-8'
        response.raise_for_status()

        data_lines = response.text.strip().split('\n')
        for line in data_lines:
            if f'var hq_str_{symbol}=' in line:
                data_str = line.split('"')[1]
                fields = data_str.split(',')

                return {
                    'symbol': symbol,
                    'price': float(fields[0]),  # 现价
                    'time': fields[6],  # 时间
                    'date': fields[12],  # 日期
                    'name': SYMBOL_NAME_MAP.get(symbol, symbol)
                }
    except Exception as e:
        print(f"[{datetime.now()}] 获取{symbol}价格失败: {e}")
    return None
