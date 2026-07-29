import time
from datetime import datetime

from config import CHINA_TZ, USD_TO_CNY_API_URL
from service.system_settings_service import SystemSettingsService
from utils.http_utils import safe_get
from utils.logger import get_logger

logger = get_logger("CurrencyUtils")

_RATE_CACHE_DURATION = 300


def _get_ounce_to_gram() -> float:
    settings = SystemSettingsService()
    monitor_config = settings.get_monitor_config()
    return monitor_config.get("ounce_to_gram", 31.1035)


def get_exchange_rate() -> float:
    """获取美元兑人民币汇率。

    策略：
    1. DB 缓存未过期（<5min）→ 直接返回
    2. 过期或无缓存 → 拉取最新 → 存入 DB → 返回
    3. 拉取失败 → 返回 DB 缓存值（即使过期）
    4. DB 也无缓存 → 抛异常
    """
    settings = SystemSettingsService()
    cached = settings.get_cached_exchange_rate()

    if cached is not None:
        row = settings.mapper.get_exchange_rate()
        if row and row.get("updated_at"):
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=CHINA_TZ
            )
            if (time.time() - updated.timestamp()) < _RATE_CACHE_DURATION:
                return cached

    rate = _fetch_from_api()
    if rate is not None:
        settings.set_cached_exchange_rate(rate)
        return rate

    if cached is not None:
        logger.warning("API 拉取失败，返回 DB 缓存汇率（可能已过期）")
        return cached

    raise RuntimeError("无法获取美元汇率：API 不可用且数据库无缓存")


def _fetch_from_api() -> float | None:
    response = safe_get(USD_TO_CNY_API_URL, timeout=10)
    if response is None:
        return None

    try:
        data = response.json()
        if data.get("result") == "success":
            rate = data["rates"].get("CNY")
            if rate:
                logger.info(f"成功获取实时汇率: {rate}")
                return float(rate)
        else:
            logger.error(f"汇率 API 返回异常: {data.get('result')}")
    except (ValueError, KeyError) as e:
        logger.error(f"解析汇率响应异常: {e}")

    return None


def convert_london_gold_to_cny(
    usd_price: float, exchange_rate: float | None = None
) -> float:
    if exchange_rate is None:
        exchange_rate = get_exchange_rate()
    cny_per_gram = (usd_price * exchange_rate) / _get_ounce_to_gram()
    return round(cny_per_gram, 2)
