import time

from providers.base import BaseExchangeRateProvider, ExchangeRateResult
from providers.currency_exchange_tool import CurrencyExchangeToolProvider
from providers.exchangerate_dev import ExchangerateDevProvider
from providers.open_er_api import OpenERApiProvider
from utils.logger import get_logger
from utils.time_utils import CHINA_TZ, now

logger = get_logger("ExchangeRateManager")

_RATE_CACHE_DURATION = 300  # 内存缓存 5 分钟
_MAX_FAILURES_BEFORE_SWITCH = 2  # 连续失败 2 次切换


class ExchangeRateProviderManager:
    """汇率数据源管理器 — 优先级链 + 失败切换 + 内存缓存"""

    def __init__(self) -> None:
        self._providers: list[BaseExchangeRateProvider] = [
            ExchangerateDevProvider(),
            CurrencyExchangeToolProvider(),
            OpenERApiProvider(),
        ]
        self._fail_counts: dict[str, int] = {
            p.provider_name: 0 for p in self._providers
        }
        self._current_index: int = 0
        self._cache: ExchangeRateResult | None = None
        self._cache_time: float = 0.0
        self._last_alerted_provider: str = ""

    def get_rate(
        self, base: str = "USD", symbol: str = "CNY"
    ) -> ExchangeRateResult | None:
        """获取汇率，按优先级链依次尝试"""
        if self._cache and (time.time() - self._cache_time) < _RATE_CACHE_DURATION:
            return self._cache

        for offset in range(len(self._providers)):
            idx = (self._current_index + offset) % len(self._providers)
            provider = self._providers[idx]
            result = self._try_fetch(provider, base, symbol)
            if result is not None:
                self._on_success(idx, result)
                return result
            self._on_failure(provider)

        logger.error("所有汇率数据源均不可用")
        return self._cache  # 返回过期缓存作为兜底

    def _try_fetch(
        self, provider: BaseExchangeRateProvider, base: str, symbol: str
    ) -> ExchangeRateResult | None:
        try:
            logger.debug(f"尝试从 {provider.provider_name} 获取汇率")
            return provider.fetch(base, symbol)
        except Exception:
            logger.exception(f"{provider.provider_name} 获取汇率时发生未预期异常")
            return None

    def _on_success(self, idx: int, result: ExchangeRateResult) -> None:
        self._fail_counts[self._providers[idx].provider_name] = 0
        if idx != self._current_index and idx < self._current_index:
            logger.info(f"汇率数据源已恢复: {self._providers[idx].provider_name}")
        self._current_index = idx
        self._cache = result
        self._cache_time = time.time()
        self._check_data_freshness(result)
        logger.info(
            f"汇率获取成功: {result.rate} (来源: {result.provider}, "
            f"数据源: {result.source}, 市场: {result.market_session})"
        )

    def _on_failure(self, provider: BaseExchangeRateProvider) -> None:
        name = provider.provider_name
        self._fail_counts[name] += 1
        count = self._fail_counts[name]
        logger.warning(f"{name} 获取失败 (连续失败 {count} 次)")

        if (
            count >= _MAX_FAILURES_BEFORE_SWITCH
            and name == self._providers[self._current_index].provider_name
        ):
            self._current_index = (self._current_index + 1) % len(self._providers)
            new_name = self._providers[self._current_index].provider_name
            logger.warning(f"汇率数据源已切换: {name} → {new_name}")

    def _check_data_freshness(self, result: ExchangeRateResult) -> None:
        if result.data_updated_at is None:
            return
        now_dt = now()
        delay_seconds = (
            now_dt - result.data_updated_at.replace(tzinfo=CHINA_TZ)
        ).total_seconds()
        if delay_seconds > 600:
            logger.warning(
                f"汇率数据延迟过大: {delay_seconds:.0f} 秒 ({result.provider})"
            )
        elif delay_seconds > 120:
            logger.info(f"汇率数据略有延迟: {delay_seconds:.0f} 秒 ({result.provider})")


_manager: ExchangeRateProviderManager | None = None


def get_rate_manager() -> ExchangeRateProviderManager:
    global _manager
    if _manager is None:
        _manager = ExchangeRateProviderManager()
    return _manager


__all__ = [
    "BaseExchangeRateProvider",
    "CurrencyExchangeToolProvider",
    "ExchangeRateProviderManager",
    "ExchangeRateResult",
    "ExchangerateDevProvider",
    "OpenERApiProvider",
    "get_rate_manager",
]
