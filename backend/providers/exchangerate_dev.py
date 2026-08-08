from datetime import datetime

from providers.base import BaseExchangeRateProvider, ExchangeRateResult
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("ExchangerateDev")

_API_URL = "https://api.exchangerate.dev/v1/latest/USD"


class ExchangerateDevProvider(BaseExchangeRateProvider):
    """主接口 — ~60 秒更新，支持 live 标记"""

    @property
    def provider_name(self) -> str:
        return "exchangerate.dev"

    def fetch(
        self, base: str = "USD", symbol: str = "CNY"
    ) -> ExchangeRateResult | None:
        response = safe_get(_API_URL, params={"symbols": symbol}, timeout=10)
        if response is None:
            return None

        try:
            data = response.json()
            if data.get("result") != "success":
                logger.error(f"exchangerate.dev 返回异常: {data.get('result')}")
                return None

            rate = data.get("rates", {}).get(symbol)
            if rate is None:
                logger.warning(f"exchangerate.dev 未找到币种 {symbol}")
                return None

            global_source = data.get("source", "")
            symbol_source = data.get("sources", {}).get(symbol, global_source)
            market_session = data.get("market_session", "")

            data_updated_raw = data.get("data_updated_at")
            data_updated_at = None
            if data_updated_raw:
                try:
                    data_updated_at = datetime.fromisoformat(data_updated_raw)
                except ValueError:
                    pass

            return ExchangeRateResult(
                base=base,
                symbol=symbol,
                rate=float(rate),
                source=symbol_source,
                market_session=market_session,
                data_updated_at=data_updated_at,
                provider=self.provider_name,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"解析 exchangerate.dev 响应异常: {e}")
            return None
