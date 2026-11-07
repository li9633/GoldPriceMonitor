from providers.price.base import FIELD_INDEX_MAP, PriceProvider, PriceQuote
from providers.price.huilvbiao import HuilvbiaoPriceProvider
from providers.price.manager import PriceProviderManager
from providers.price.sina import SinaPriceProvider

_manager: PriceProviderManager | None = None


def get_price_manager() -> PriceProviderManager:
    global _manager
    if _manager is None:
        _manager = PriceProviderManager()
    return _manager


__all__ = [
    "FIELD_INDEX_MAP",
    "HuilvbiaoPriceProvider",
    "PriceProvider",
    "PriceProviderManager",
    "PriceQuote",
    "SinaPriceProvider",
    "get_price_manager",
]
