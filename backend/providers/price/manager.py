"""金价数据源管理器 —— 优先级链 + 失败切换（对齐汇率 manager 的模式）。

huilvbiao 为主源，新浪为备源；连续失败 2 次切换，高优先级恢复后自动回切。
每次调用会从当前主源开始逐个尝试 —— 单源故障时最多多花一次超时。
"""

from providers.price.base import PriceProvider, PriceQuote
from providers.price.huilvbiao import HuilvbiaoPriceProvider
from providers.price.sina import SinaPriceProvider
from utils.logger import get_logger

logger = get_logger("PriceProviderManager")

_MAX_FAILURES_BEFORE_SWITCH = 2


class PriceProviderManager:
    def __init__(self, providers: list[PriceProvider] | None = None) -> None:
        self._providers: list[PriceProvider] = providers or [
            HuilvbiaoPriceProvider(),
            SinaPriceProvider(),
        ]
        self._fail_counts: dict[str, int] = {
            p.provider_name: 0 for p in self._providers
        }
        self._current_index = 0

    @property
    def current_provider(self) -> str:
        return self._providers[self._current_index].provider_name

    def fetch(self, symbol: str) -> PriceQuote | None:
        for offset in range(len(self._providers)):
            idx = (self._current_index + offset) % len(self._providers)
            provider = self._providers[idx]
            try:
                quote = provider.fetch(symbol)
            except Exception:  # noqa: BLE001
                logger.exception(f"{provider.provider_name} 获取 {symbol} 时未预期异常")
                quote = None

            if quote is not None:
                self._on_success(idx)
                return quote
            self._on_failure(idx, symbol)
        logger.error(f"所有金价数据源均不可用：{symbol}")
        return None

    def _on_success(self, idx: int) -> None:
        name = self._providers[idx].provider_name
        self._fail_counts[name] = 0
        if idx < self._current_index:
            logger.info(f"金价数据源已恢复: {name}")
        self._current_index = idx

    def _on_failure(self, idx: int, symbol: str) -> None:
        provider = self._providers[idx]
        name = provider.provider_name
        self._fail_counts[name] = self._fail_counts.get(name, 0) + 1
        count = self._fail_counts[name]
        logger.warning(f"{name} 获取 {symbol} 失败（连续失败 {count} 次）")
        if count >= _MAX_FAILURES_BEFORE_SWITCH and idx == self._current_index:
            self._current_index = (self._current_index + 1) % len(self._providers)
            logger.warning(
                f"金价数据源已切换: {name} → "
                f"{self._providers[self._current_index].provider_name}"
            )
