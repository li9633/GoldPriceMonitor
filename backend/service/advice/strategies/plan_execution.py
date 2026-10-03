"""计划执行策略：有进行中的购买计划时，判断「这一批该不该买」。

优先级最高 —— 用户已经定好了分批计划，系统要做的是帮他执行，而不是另起炉灶。
"""

from models.advice import AdviceAction, AdviceDraft, AdviceKind, Signal
from service.advice.context import AdviceContext
from service.advice.signals import has
from service.advice.strategies.common import (
    confidence_from,
    market_context_text,
    price_band_around,
)


def build(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    state = ctx.active_plan
    assert state is not None  # 由 dispatch 保证

    base = dict(
        kind=AdviceKind.PLAN_EXECUTION,
        symbol=ctx.symbol,
        signals=signals,
        evidence=ctx.to_evidence(),
        confidence=confidence_from(signals),
    )

    if has(signals, "no_market_data"):
        return AdviceDraft(
            action=AdviceAction.WAIT,
            rationale="缺少行情数据，无法判断本批是否适合买入，建议等数据恢复后再执行计划",
            **base,
        )

    if has(signals, "position_ratio_high"):
        return AdviceDraft(
            action=AdviceAction.HOLD,
            rationale=(
                f"{market_context_text(ctx)}。持仓市值已占总可投资金 "
                f"{ctx.position_ratio_pct():.0f}%，仓位偏重，本批建议暂缓执行计划"
            ),
            **base,
        )

    if not state.due_by_interval() and not state.due_by_drop(ctx.current_price):
        policy = state.trigger_policy
        if policy.get("type") == "interval":
            due_hint = (
                f"距上次买入 {state.days_since_last_lot} 天，"
                f"未到 {policy.get('days')} 天的间隔"
                if state.days_since_last_lot is not None
                else "尚未开始建仓"
            )
        elif policy.get("type") == "drop_pct":
            due_hint = (
                f"现价 ¥{ctx.current_price:.2f} 尚未较上次买入价 "
                f"¥{state.last_lot_price:.2f} 回落 {policy.get('pct')}%"
                if state.last_lot_price
                else "尚未开始建仓"
            )
        else:
            due_hint = "计划未设置触发条件"
        return AdviceDraft(
            action=AdviceAction.WAIT,
            rationale=f"{market_context_text(ctx)}。{due_hint}，本批不急于买入",
            **base,
        )

    grams = state.next_tranche_grams()
    low, high = price_band_around(ctx.current_price)
    progress = state.progress
    trigger = state.trigger_policy
    if trigger.get("type") == "drop_pct" and state.last_lot_price:
        reason = (
            f"现价 ¥{ctx.current_price:.2f} 较上次买入价 ¥{state.last_lot_price:.2f} "
            f"已回落，达到 {trigger.get('pct')}% 的补仓条件"
        )
    elif trigger.get("type") == "interval":
        reason = (
            f"距上次买入已 {state.days_since_last_lot} 天，达到 "
            f"{trigger.get('days')} 天的间隔"
            if state.days_since_last_lot is not None
            else "计划尚未开始建仓"
        )
    else:
        reason = "计划本批已到点"

    return AdviceDraft(
        action=AdviceAction.BUY_PARTIAL,
        target_grams=grams,
        price_band_low=low,
        price_band_high=high,
        rationale=(
            f"{reason}。{market_context_text(ctx)}。"
            f"建议按计划买入约 {grams}g，完成后进度 "
            f"{progress.filled_grams + grams:.1f}/{progress.target_grams:.0f}g"
        ),
        **base,
    )
