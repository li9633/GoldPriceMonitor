"""策略共用的小工具：建议克数、价位区间、置信度。

这些是**算术**，必须留在代码里，绝不能交给 LLM 去估。
"""

from models.advice import Signal
from service.advice.context import AdviceContext


def suggest_buy_grams(ctx: AdviceContext, fraction: float = 1.0) -> float | None:
    """在偏好允许的范围内给出建议买入克数。

    `fraction` 用于「分批」——只买剩余额度的一部分（例如 1/3）。

    返回 `None` 表示**偏好没配**，此时只能给方向（买/等），给不出数量；
    返回 `0.0` 表示额度已用尽，应当观望。
    """
    price = ctx.current_price
    if price <= 0:
        return None

    candidates: list[float] = []
    if ctx.prefs.target_grams > 0:
        remaining_target = ctx.prefs.target_grams - ctx.position.total_grams
        if remaining_target <= 0:
            return 0.0
        candidates.append(remaining_target)
    if ctx.prefs.total_investable > 0:
        remaining_budget = ctx.prefs.total_investable - ctx.position.total_cost
        if remaining_budget <= 0:
            return 0.0
        candidates.append(remaining_budget / price)

    if not candidates:
        return None

    base = min(candidates)
    return round(max(base * fraction, 0.0), 4)


def suggest_sell_grams(ctx: AdviceContext, fraction: float) -> float | None:
    """建议减持克数（按当前持仓的比例）"""
    if ctx.position.total_grams <= 0:
        return None
    return round(ctx.position.total_grams * fraction, 4)


def price_band_around(price: float, pct: float = 0.5) -> tuple[float, float]:
    """给出一个「可接受的下单区间」，避免建议只说一个点"""
    return (round(price * (1 - pct / 100), 2), round(price * (1 + pct / 100), 2))


def confidence_from(signals: list[Signal]) -> float:
    """由信号强弱给出置信度 —— 让「有把握」和「说不准」在界面上可区分"""
    ids = {signal.id for signal in signals}
    score = 0.5
    if "no_market_data" in ids:
        score -= 0.3
    if "long_term_low_3m" in ids or "long_term_low_6m" in ids:
        score += 0.2
    if "plan_due" in ids:
        score += 0.15
    if "high_volatility" in ids:
        score -= 0.1
    if "position_ratio_high" in ids:
        score += 0.05
    if "deep_loss" in ids:
        score += 0.05
    return round(min(max(score, 0.1), 0.9), 2)


def summarize_signals(signals: list[Signal], limit: int = 3) -> str:
    """把最关键的几条信号拼成一句人话，供规则版理由使用"""
    priority = {"critical": 0, "warning": 1, "notice": 2, "info": 3}
    ordered = sorted(signals, key=lambda s: priority.get(s.severity, 9))
    picked = [signal.summary for signal in ordered[:limit]]
    return "；".join(picked)


def market_context_text(ctx: AdviceContext) -> str:
    """行情一句话，用于理由开头"""
    ind = ctx.indicators
    parts = [f"现价 ¥{ind.current_price:.2f}/克"]
    if ind.min_3m and ind.pct_from_3m_low is not None:
        parts.append(f"距近 90 日低点 {ind.pct_from_3m_low:+.2f}%")
    if ind.trend_24h_direction:
        direction = {"up": "上涨", "down": "下跌", "stable": "横盘"}[
            ind.trend_24h_direction
        ]
        parts.append(f"中期趋势{direction}")
    return "，".join(parts)
