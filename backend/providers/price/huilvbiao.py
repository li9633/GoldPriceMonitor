"""huilvbiao 数据源 —— 现有主源，解析逻辑自 `PriceService` 原样迁入。

`GOLD_PRICE_API_URL` 返回新浪格式的文本（每行 `var hq_str_<symbol>="..."`），
字段位置见 `FIELD_INDEX_MAP`。行为与迁移前逐字节一致。
"""

import time

from config import GOLD_PRICE_API_URL
from providers.price.base import FIELD_INDEX_MAP, PriceProvider, PriceQuote
from utils.http_utils import safe_get
from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("HuilvbiaoProvider")


class HuilvbiaoPriceProvider(PriceProvider):
    @property
    def provider_name(self) -> str:
        return "huilvbiao"

    def fetch(self, symbol: str) -> PriceQuote | None:
        try:
            timestamp = int(time.time() * 1000)
            url = f"{GOLD_PRICE_API_URL}?t={timestamp}"
            response = safe_get(url, timeout=10)
            if response is None:
                return None

            data_lines = response.text.strip().split("\n")
            for line in data_lines:
                if f"var hq_str_{symbol}=" in line:
                    parts = line.split('"')
                    if len(parts) < 2:
                        logger.warning(f"[{now()}] 解析{symbol}数据格式错误")
                        continue

                    data_str = parts[1]
                    fields = data_str.split(",")
                    indices = FIELD_INDEX_MAP["default"]

                    max_index_needed = max(indices.values())
                    if len(fields) <= max_index_needed:
                        logger.warning(
                            f"[{now()}] 解析{symbol}数据字段不足 ({len(fields)})"
                        )
                        continue

                    try:
                        return PriceQuote(
                            symbol=symbol,
                            price=float(fields[indices["price"]]),
                            trade_time=fields[indices["time"]],
                            trade_date=fields[indices["date"]],
                        )
                    except (ValueError, IndexError) as e:
                        logger.error(f"[{now()}] 转换{symbol}数据字段失败: {e}")
                        continue

        except Exception as e:  # noqa: BLE001
            logger.error(f"[{now()}] 获取{symbol}价格网络请求失败: {e}")

        return None
