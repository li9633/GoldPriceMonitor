"""策略调度。

优先级：复盘 > 计划执行 > 购买后 > 购买前。

- **复盘**：带上 `subject_lot` 时，这是针对某笔买入的 T+n 回访；动作沿用常规判断
  （见 `review.build`）。
- **计划执行**：用户已有分批计划时，系统做的是执行计划，不另起炉灶给买点建议。
"""

from models.advice import AdviceDraft, AdviceKind, Signal
from service.advice.context import AdviceContext
from service.advice.strategies import (
    plan_execution,
    post_purchase,
    pre_purchase,
    review,
)

__all__ = ["build_advice", "build_regular", "select_kind"]

_REGULAR_BUILDERS = {
    AdviceKind.PLAN_EXECUTION: plan_execution.build,
    AdviceKind.POST_PURCHASE: post_purchase.build,
    AdviceKind.PRE_PURCHASE: pre_purchase.build,
}

_ALL_BUILDERS = {**_REGULAR_BUILDERS, AdviceKind.REVIEW: review.build}


def select_kind(ctx: AdviceContext) -> AdviceKind:
    if ctx.is_review:
        return AdviceKind.REVIEW
    return regular_kind(ctx)


def regular_kind(ctx: AdviceContext) -> AdviceKind:
    """常规判断（不把 `ctx` 当作复盘）"""
    if ctx.active_plan is not None:
        return AdviceKind.PLAN_EXECUTION
    if ctx.has_position:
        return AdviceKind.POST_PURCHASE
    return AdviceKind.PRE_PURCHASE


def build_regular(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    """按常规逻辑出建议 —— 复盘策略用它复用同一套动作判断"""
    return _REGULAR_BUILDERS[regular_kind(ctx)](ctx, signals)


def build_advice(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    return _ALL_BUILDERS[select_kind(ctx)](ctx, signals)
