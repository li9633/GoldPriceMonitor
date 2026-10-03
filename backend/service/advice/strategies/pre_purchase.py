"""购买前策略：还没有持仓时，判断「要不要买、这次买多少、一次买满还是分批」。

「一次性还是分批」的判断**以历史回测为准**（`entry_strategy`，阶段 3）：在同一段
历史里找出与当前波动率相似的环境，比较一次性与各种分批方案的实际持有成本。
数据不足以回测时，才退回「波动高/位置高就分批」的经验规则。
"""

from models.advice import AdviceAction, AdviceDraft, AdviceKind, Signal
from service.advice.context import AdviceContext
from service.advice.signals import has
from service.advice.strategies.common import (
    confidence_from,
    market_context_text,
    price_band_around,
    suggest_buy_grams,
)

#: 回测不可用时的经验兜底批次数
FALLBACK_TRANCHES = 3


def _suggested_tranches(ctx: AdviceContext, signals: list[Signal]) -> tuple[int, str]:
    """决定一次买满还是分几批，并给出理由。

    返回 `(批次数, 理由)`；批次数为 1 表示一次性买入。
    """
    result = ctx.entry_strategy
    if result is not None and result.sufficient_data:
        return result.recommended_tranches, result.explanation

    # 回测不可用（历史数据不足）→ 退回经验规则，并在理由里说明依据不足
    if (
        has(signals, "high_volatility")
        or has(signals, "near_24h_high")
        or has(signals, "trend_mid_down")
    ):
        return (
            FALLBACK_TRANCHES,
            "历史数据不足以回测建仓方式，按经验：波动或位置偏高时先买三分之一",
        )
    return 1, ""


def build(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    base = dict(
        kind=AdviceKind.PRE_PURCHASE,
        symbol=ctx.symbol,
        signals=signals,
        evidence=ctx.to_evidence(),
        confidence=confidence_from(signals),
    )

    if has(signals, "no_market_data"):
        return AdviceDraft(
            action=AdviceAction.WAIT,
            rationale="缺少行情数据，暂时无法判断买点，建议等数据恢复后再看",
            **base,
        )

    at_long_term_low = has(signals, "long_term_low_3m") or has(signals, "long_term_low_6m")
    downtrend = has(signals, "trend_mid_down")
    uptrend = has(signals, "trend_mid_up")
    high_volatility = has(signals, "high_volatility")
    near_high = has(signals, "near_24h_high")
    far_from_low = has(signals, "far_from_long_term_low")

    # 价格已远离长期低点、又处在当日区间上沿且在上涨 → 别追高
    if far_from_low and near_high and uptrend:
        return AdviceDraft(
            action=AdviceAction.AVOID,
            rationale=(
                f"{market_context_text(ctx)}。价格已明显高于长期低点，"
                "又处在近 24 小时区间上沿且趋势向上，此时买入属于追高，"
                "建议等回调或改用分批方式摊薄成本"
            ),
            **base,
        )

    tranches, method_reason = _suggested_tranches(ctx, signals)
    budget_grams = suggest_buy_grams(ctx)

    # ---- 分批 ----
    if tranches > 1:
        batch = suggest_buy_grams(ctx, fraction=1 / tranches)
        low, high = price_band_around(ctx.current_price, 0.8)
        reasons = [
            label
            for label, flag in (
                ("波动偏高", high_volatility),
                ("处于近 24 小时区间上沿", near_high),
                ("中期趋势向下", downtrend),
            )
            if flag
        ]
        suffix = f"，{'、'.join(reasons)}" if reasons else ""
        if batch:
            amount_text = (
                f"建议先买约 {batch}g（约 1/{tranches} 额度），"
                "剩余额度按同样节奏分批补入"
            )
        else:
            amount_text = (
                f"建议分 {tranches} 批逐步建仓；未配置目标克数/总资金，"
                "因此给不出具体数量"
            )
        return AdviceDraft(
            action=AdviceAction.BUY_PARTIAL,
            target_grams=batch,
            price_band_low=low,
            price_band_high=high,
            rationale=f"{market_context_text(ctx)}{suffix}。{method_reason}。{amount_text}",
            **base,
        )

    # ---- 一次性 ----
    grams = budget_grams if budget_grams is not None else None
    low, high = price_band_around(ctx.current_price)
    if at_long_term_low and not downtrend:
        position_text = "价格贴近长期低点且中期趋势未继续走坏，是不错的建仓位置"
    else:
        position_text = "位置与趋势均无异常"
    if method_reason:
        position_text = f"{position_text}；{method_reason}"
    amount_text = f"建议买入约 {grams}g" if grams else "建议买入"
    rationale = (
        f"{market_context_text(ctx)}。{position_text}，{amount_text}"
        + ("。" if grams else "；未配置目标克数/总资金，因此只给方向、不给数量。")
    )
    return AdviceDraft(
        action=AdviceAction.BUY_NOW,
        target_grams=grams,
        price_band_low=low,
        price_band_high=high,
        rationale=rationale,
        **base,
    )
