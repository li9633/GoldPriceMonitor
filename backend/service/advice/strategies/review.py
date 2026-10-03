"""复盘策略：买入后 T+1 / T+7 / T+30 主动回访「你这笔买得怎么样」。

动作沿用常规判断（计划优先 → 购买后 → 购买前），复盘只补上针对这一笔买入的交代。
不另起一套判断，避免出现「复盘说补仓、常规建议说观望」这种自相矛盾的输出。
"""

from models.advice import AdviceDraft, AdviceKind, Signal
from service.advice.context import AdviceContext


def build(ctx: AdviceContext, signals: list[Signal]) -> AdviceDraft:
    # 函数内导入：`strategies/__init__` 需要 import 本模块来注册调度表，
    # 模块级导入 `build_regular` 会形成循环。
    from service.advice.strategies import build_regular

    inner = build_regular(ctx, signals)

    lot = ctx.subject_lot or {}
    horizon = ctx.review_horizon
    entry = _as_float(lot.get("price_per_gram"))
    grams = _as_float(lot.get("grams"))
    trade_date = lot.get("trade_date")
    lot_pnl = ctx.lot_pnl_pct()

    if entry and grams:
        header = (
            f"回访你在 {trade_date} 买入的 {grams:g}g（成交价 ¥{entry:.2f}/克）："
            f"到今天 T+{horizon}"
        )
        header += (
            f"，这笔浮动 {lot_pnl:+.2f}%。" if lot_pnl is not None else "。"
        )
    else:  # pragma: no cover - 买入记录的克数与单价都是必填
        header = f"回访你在 {trade_date} 的这笔买入（T+{horizon}）。"

    return AdviceDraft(
        kind=AdviceKind.REVIEW,
        action=inner.action,
        symbol=inner.symbol,
        target_grams=inner.target_grams,
        price_band_low=inner.price_band_low,
        price_band_high=inner.price_band_high,
        confidence=inner.confidence,
        rationale=f"{header}{inner.rationale}",
        signals=inner.signals,
        evidence=inner.evidence,
    )


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
