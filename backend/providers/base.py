from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExchangeRateResult:
    """统一的汇率结果，屏蔽不同 API 的数据格式差异"""

    base: str = "USD"
    symbol: str = "CNY"
    rate: float = 0.0
    source: str = ""  # live / ecb_daily / yahoo_live
    market_session: str = ""  # open / weekend / holiday
    data_updated_at: datetime | None = None
    provider: str = ""


class BaseExchangeRateProvider(ABC):
    """汇率数据源抽象基类"""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def fetch(
        self, base: str = "USD", symbol: str = "CNY"
    ) -> ExchangeRateResult | None: ...

    def is_available(self) -> bool:
        """健康检查，子类可覆盖"""
        return True
