"""购买后策略：已有持仓时，判断「持有 / 补仓 / 止盈 / 止损」。

这是把建议从「无主体文案」变成「针对你的成本」的关键 —— 判断依据是
**持仓成本与浮盈亏**，而不是单纯的价格高低。
"""

from models.advice import AdviceAction, AdviceDraft, AdviceKind, Signal
from service.advice.context import AdviceContext
from service.advice.signals import has
from service.advice.strategies.common import (
    DraftBase,
    confidence_from,
    price_band_around,
    suggest_buy_grams,
    suggest_sell_grams,
)

#: 止盈时建议卖出的比例（分批止盈，不一次清仓）
TAKE_PROFIT_FRACTION = 1 / 3
#: 止损时建议卖出的比例
STOP_LOSS_FRACTION = 0.5
#: 浮亏补仓时使用的剩余额度比例（再按风险偏好缩放）
BOUNCE_FRACTION = 0.5


def build(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    base: DraftBase = {
        "kind": AdviceKind.POST_PURCHASE,
        "symbol": ctx.symbol,
        "signals": signals,
        "evidence": ctx.to_evidence(),
        "confidence": confidence_from(signals),
    }
    position = ctx.position
    pnl_pct = position.unrealized_pnl_pct

    if has(signals, "no_market_data") or pnl_pct is None:
        return AdviceDraft(
            action=AdviceAction.HOLD,
            rationale=(
                f"持仓 {position.total_grams}g，成本价 ¥{position.avg_cost:.2f}；"
                "缺少当前行情，暂时无法评估盈亏，先持有观察"
            ),
            **base,
        )

    cost_text = (
        f"持仓 {position.total_grams}g，成本价 ¥{position.avg_cost:.2f}，"
        f"现价 ¥{ctx.current_price:.2f}（{pnl_pct:+.2f}%）"
    )

    # ---- 深度浮亏 + 趋势继续走坏 → 止损 ----
    if has(signals, "deep_loss") and has(signals, "trend_mid_down"):
        grams = suggest_sell_grams(ctx, STOP_LOSS_FRACTION)
        low, high = price_band_around(ctx.current_price, 0.8)
        return AdviceDraft(
            action=AdviceAction.STOP_LOSS,
            target_grams=grams,
            price_band_low=low,
            price_band_high=high,
            rationale=(
                f"{cost_text}。浮亏已超过 {ctx.risk.deep_loss_pct:g}% 阈值"
                f"（{ctx.risk.label}档）且中期趋势仍在向下，"
                f"建议减仓约 {grams}g 控制风险，避免亏损继续扩大"
            ),
            **base,
        )

    # ---- 浮亏但已到长期低位 → 补仓 ----
    if has(signals, "in_loss") or has(signals, "deep_loss"):
        at_low = has(signals, "long_term_low_3m") or has(signals, "long_term_low_6m")
        if at_low and not has(signals, "position_ratio_high"):
            fraction = ctx.risk.buy_fraction(BOUNCE_FRACTION)
            grams = suggest_buy_grams(ctx, fraction=BOUNCE_FRACTION)
            low, high = price_band_around(ctx.current_price)
            if grams is None:
                return AdviceDraft(
                    action=AdviceAction.HOLD,
                    rationale=(
                        f"{cost_text}。价格已到长期低位，具备补仓价值，"
                        "但未配置目标克数/总资金，无法给出补仓数量；先持有并补全配置"
                    ),
                    **base,
                )
            if grams == 0.0:
                return AdviceDraft(
                    action=AdviceAction.HOLD,
                    rationale=f"{cost_text}。额度已用尽，无法补仓，建议持有等待",
                    **base,
                )
            return AdviceDraft(
                action=AdviceAction.ADD,
                target_grams=grams,
                price_band_low=low,
                price_band_high=high,
                rationale=(
                    f"{cost_text}。价格处于长期低位，补仓可摊低成本，"
                    f"建议加约 {grams}g（剩余额度的 {fraction:.0%}，{ctx.risk.label}档）"
                ),
                **base,
            )
        return AdviceDraft(
            action=AdviceAction.HOLD,
            rationale=f"{cost_text}。虽有浮亏但尚未到长期低位，建议持有观察，不急于补仓",
            **base,
        )

    # ---- 浮盈较多 → 分批止盈 ----
    if has(signals, "big_profit"):
        sell_fraction = ctx.risk.sell_fraction(TAKE_PROFIT_FRACTION, take_profit=True)
        grams = suggest_sell_grams(ctx, TAKE_PROFIT_FRACTION, take_profit=True)
        low, high = price_band_around(ctx.current_price, 0.8)
        return AdviceDraft(
            action=AdviceAction.TAKE_PROFIT,
            target_grams=grams,
            price_band_low=low,
            price_band_high=high,
            rationale=(
                f"{cost_text}。浮盈已达到 {ctx.risk.profit_pct:g}% 阈值"
                f"（{ctx.risk.label}档），建议分批锁定收益，"
                f"先卖出约 {grams}g（持仓的 {sell_fraction:.0%}），剩余继续持有"
            ),
            **base,
        )

    # ---- 其余情况：持有 ----
    if pnl_pct >= 0:
        hint = "小幅浮盈，继续持有即可" if pnl_pct > 0 else "基本持平，继续持有即可"
    else:
        hint = "浮亏尚未到补仓阈值，继续持有并等待更好的位置"
    return AdviceDraft(
        action=AdviceAction.HOLD, rationale=f"{cost_text}。{hint}", **base
    )
