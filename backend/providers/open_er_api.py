from datetime import UTC, datetime

from providers.base import BaseExchangeRateProvider, ExchangeRateResult
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("OpenERApi")

_API_URL = "https://open.er-api.com/v6/latest/USD"


class OpenERApiProvider(BaseExchangeRateProvider):
    """降级兜底接口 — 每日更新，免费稳定"""

    @property
    def provider_name(self) -> str:
        return "open.er-api"

    def fetch(
        self, base: str = "USD", symbol: str = "CNY"
    ) -> ExchangeRateResult | None:
        response = safe_get(_API_URL, timeout=10)
        if response is None:
            return None

        try:
            data = response.json()
            if data.get("result") != "success":
                logger.error(f"open.er-api 返回异常: {data.get('result')}")
                return None

            rate = data.get("rates", {}).get(symbol)
            if rate is None:
                logger.warning(f"open.er-api 未找到币种 {symbol}")
                return None

            last_update = data.get("time_last_update_unix")
            data_updated_at = (
                datetime.fromtimestamp(last_update, tz=UTC) if last_update else None
            )

            return ExchangeRateResult(
                base=base,
                symbol=symbol,
                rate=float(rate),
                source="daily",
                market_session="",
                data_updated_at=data_updated_at,
                provider=self.provider_name,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"解析 open.er-api 响应异常: {e}")
            return None
