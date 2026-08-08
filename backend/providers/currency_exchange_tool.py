from datetime import datetime

from providers.base import BaseExchangeRateProvider, ExchangeRateResult
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("CurrencyExchangeTool")

_API_URL = "https://www.currencyexchangetool.com/api/v1/convert"


class CurrencyExchangeToolProvider(BaseExchangeRateProvider):
    """备接口 — 实时拉 Yahoo 数据"""

    @property
    def provider_name(self) -> str:
        return "currencyexchangetool"

    def fetch(
        self, base: str = "USD", symbol: str = "CNY"
    ) -> ExchangeRateResult | None:
        response = safe_get(
            _API_URL, params={"amount": 1, "from": base, "to": symbol}, timeout=10
        )
        if response is None:
            return None

        try:
            data = response.json()
            if not data.get("success"):
                logger.error("currencyexchangetool 返回失败")
                return None

            rate = data.get("rate")
            if rate is None:
                logger.warning("currencyexchangetool 未获取到汇率")
                return None

            updated_raw = data.get("updatedAt")
            data_updated_at = None
            if updated_raw:
                try:
                    data_updated_at = datetime.fromisoformat(updated_raw)
                except ValueError:
                    pass

            return ExchangeRateResult(
                base=base,
                symbol=symbol,
                rate=float(rate),
                source="yahoo_live",
                market_session="",
                data_updated_at=data_updated_at,
                provider=self.provider_name,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"解析 currencyexchangetool 响应异常: {e}")
            return None
