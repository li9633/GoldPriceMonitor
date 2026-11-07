"""非建议类触发器的公共工具：配置读取、涨跌幅、持仓摘要。"""

from service.position import compute_position
from utils.logger import get_logger

logger = get_logger("TriggerCommon")

#: 触发器配置默认值（与 advice_config 表列默认一致）
TRIGGER_CONFIG_DEFAULTS = {
    "volatility_enabled": True,
    "volatility_trigger_pct": 1.0,
    "volatility_critical_pct": 2.5,
    "volatility_cooldown_minutes": 60.0,
    "digest_enabled": True,
    "digest_time": "20:00",
    "reopen_gap_enabled": True,
    "reopen_gap_time": "20:00",
}


def trigger_config(settings) -> dict:
    """读取触发器配置，缺省键补默认值（存量库未迁移时也能工作）"""
    try:
        raw = settings.get_advice_config() or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取触发器配置失败，使用默认值：{exc}", exc_info=exc)
        raw = {}
    config = dict(TRIGGER_CONFIG_DEFAULTS)
    for key in TRIGGER_CONFIG_DEFAULTS:
        if key in raw and raw[key] is not None:
            config[key] = raw[key]
    return config


def pct_change(new: float, old: float) -> float | None:
    """百分比变化（带方向）；基准非正时返回 None"""
    if not old or old <= 0:
        return None
    return (new - old) / old * 100


def fmt_pct(move: float | None) -> str:
    if move is None:
        return "—"
    return f"{move:+.2f}%"


def position_summary(
    portfolio_mapper, symbol: str, latest_price: float
) -> dict | None:
    """持仓摘要（有持仓才返回）；字段名已适合直接放进消息 fields"""
    try:
        lots = portfolio_mapper.list_lots(symbol)
        sales = portfolio_mapper.list_sales(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取持仓记录失败 symbol={symbol}：{exc}", exc_info=exc)
        return None
    if not lots:
        return None
    try:
        position = compute_position(
            symbol, lots, latest_price=latest_price, sales=sales
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"计算持仓摘要失败 symbol={symbol}：{exc}", exc_info=exc)
        return None
    if not position or position.total_grams <= 0:
        return None
    summary = {"持仓": f"{position.total_grams:g}g"}
    if position.unrealized_pnl_pct is not None:
        summary["持仓浮盈"] = f"{position.unrealized_pnl_pct:+.2f}%"
    if position.unrealized_pnl is not None:
        summary["浮动盈亏"] = f"¥{position.unrealized_pnl:+,.0f}"
    return summary


def parse_hhmm(value: str) -> tuple[int, int]:
    """'20:00' → (20, 0)；解析失败回落 20:00"""
    try:
        hour, minute = str(value).split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 20, 0


def price_24h_change(price_mapper, symbol: str) -> float | None:
    """24 小时涨跌幅：序列首尾对比；数据不足返回 None"""
    try:
        series = price_mapper.get_price_series(symbol, 24)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取 24h 价格序列失败 symbol={symbol}：{exc}", exc_info=exc)
        return None
    if not series or len(series) < 2:
        return None
    return pct_change(float(series[-1][1]), float(series[0][1]))


def is_after(at_time_tuple: tuple[int, int], configured: str) -> bool:
    now_hm = (at_time_tuple[0], at_time_tuple[1])
    return now_hm >= parse_hhmm(configured)
