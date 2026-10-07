"""新浪财经数据源 —— huilvbiao 的同源备胎。

接口：`https://hq.sinajs.cn/list=<symbol>`（gds_* 上金所品种、hf_* 国际金），
字段布局与 huilvbiao 完全一致（price=0, time=6, date=12，2026-10-07 实测）。

与 huilvbiao 的差异：
- 必须带 `Referer: https://finance.sina.com.cn`（防盗链）；
- 返回 GBK 编码（价格/时间为 ASCII，不受影响，但需自行设置编码取品种名）；
- 空行（如 `var hq_str_gds_au9999=""`）表示当前无数据 → None。

因此不走 `safe_get`（它强制 utf-8 且不带 Referer），直接用 requests。
"""

import requests

from providers.price.base import FIELD_INDEX_MAP, PriceProvider, PriceQuote
from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("SinaProvider")

_API_URL = "https://hq.sinajs.cn/list={symbol}"
_TIMEOUT = 10

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
}


class SinaPriceProvider(PriceProvider):
    @property
    def provider_name(self) -> str:
        return "sina"

    def fetch(self, symbol: str) -> PriceQuote | None:
        try:
            response = requests.get(
                _API_URL.format(symbol=symbol), headers=_HEADERS, timeout=_TIMEOUT
            )
            response.raise_for_status()
            response.encoding = "gbk"
            return self._parse(symbol, response.text)
        except requests.RequestException as e:
            logger.error(f"[{now()}] 新浪获取{symbol}价格失败: {e}")
            return None

    @staticmethod
    def _parse(symbol: str, text: str) -> PriceQuote | None:
        for line in text.strip().split("\n"):
            if f"var hq_str_{symbol}=" not in line:
                continue
            parts = line.split('"')
            if len(parts) < 2 or not parts[1]:
                logger.warning(f"[{now()}] 新浪返回 {symbol} 无数据")
                return None

            fields = parts[1].split(",")
            indices = FIELD_INDEX_MAP["default"]
            if len(fields) <= max(indices.values()):
                logger.warning(
                    f"[{now()}] 新浪解析{symbol}数据字段不足 ({len(fields)})"
                )
                return None
            try:
                return PriceQuote(
                    symbol=symbol,
                    price=float(fields[indices["price"]]),
                    trade_time=fields[indices["time"]],
                    trade_date=fields[indices["date"]],
                )
            except (ValueError, IndexError) as e:
                logger.error(f"[{now()}] 新浪转换{symbol}数据字段失败: {e}")
                return None
        logger.warning(f"[{now()}] 新浪响应中不含 {symbol} 数据行")
        return None
