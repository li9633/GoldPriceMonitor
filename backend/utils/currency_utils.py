import sqlite3

from mapper.exchange_rate_mapper import ExchangeRateMapper
from providers import get_rate_manager
from providers.base import ExchangeRateResult
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

logger = get_logger("CurrencyUtils")


def _get_ounce_to_gram() -> float:
    settings = SystemSettingsService()
    monitor_config = settings.get_monitor_config()
    return monitor_config.get("ounce_to_gram", 31.1035)


def get_usd_exchange() -> float:
    """获取美元兑人民币汇率。

    调用方无需关心数据源，内部自动处理：
    1. 主接口 → 备接口 → 降级接口 优先级链
    2. 全部接口失败 → 返回数据库最新一条记录作为兜底
    3. 数据库也无记录 → 抛出 RuntimeError
    """
    manager = get_rate_manager()
    result = manager.get_rate()
    if result is not None:
        _save_to_history(result)
        return result.rate

    db_rate = ExchangeRateMapper().get_latest_rate()
    if db_rate is not None:
        logger.warning("所有数据源不可用，返回数据库最新汇率作为兜底")
        return db_rate

    raise RuntimeError("无法获取美元汇率：所有数据源不可用且数据库无缓存")


def _save_to_history(result: ExchangeRateResult) -> None:
    try:
        data_ts = 0
        if result.data_updated_at is not None:
            data_ts = int(result.data_updated_at.timestamp())
        ExchangeRateMapper().save_rate(
            rate=result.rate,
            source=result.source,
            provider=result.provider,
            data_updated_at=data_ts,
        )
    except sqlite3.Error as e:
        logger.warning(f"汇率写入历史表失败（不影响主流程）：{e}")


def convert_london_gold_to_cny(
    usd_price: float, exchange_rate: float | None = None
) -> float:
    if exchange_rate is None:
        exchange_rate = get_usd_exchange()
    cny_per_gram = (usd_price * exchange_rate) / _get_ounce_to_gram()
    return round(cny_per_gram, 2)
