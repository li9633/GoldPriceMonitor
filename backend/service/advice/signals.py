"""确定性信号 —— 建议的事实依据。

每个信号只做一件事：把某个判断连同支撑它的数值一起说出来。策略再基于这一组信号
做决策。这样拆的价值：

- **可单测**：给定指标就能断言命中哪些信号；
- **可回测**：信号是纯函数，没有副作用；
- **LLM 挂了不影响结论**：它只负责把结论说得更好听，算术和判断都在这里。

阈值都集中在文件顶部，方便按风险偏好调整。
"""

from models.advice import Signal, SignalCategory
from service.advice.context import AdviceContext

# ---- 位置类 ----
NEAR_LOW_TOLERANCE_PCT = 0.5  # 距 3/6 个月低点 0.5% 以内算「贴近长期低点」
BOTTOM_RANGE_POSITION = 0.2  # 处于 24 小时区间下沿 20%
TOP_RANGE_POSITION = 0.8  # 处于 24 小时区间上沿 80%

# ---- 趋势 ----
HIGH_VOLATILITY_PCT = 0.8  # 24 小时波动率（std/avg）
MA_GAP_PCT = 1.0  # 与 20 周期均线的距离在此以内算「缠绕」
FAR_FROM_LOW_PCT = 15.0  # 高于近 180 日低点此比例以上，算「已经不便宜」

# ---- 持仓类 ----
DEEP_LOSS_PCT = -10.0  # 浮亏超过此比例触发止损提示
LOSS_PCT = -3.0  # 浮亏超过此比例考虑补仓
PROFIT_PCT = 8.0  # 浮盈超过此比例考虑部分止盈
POSITION_RATIO_HIGH_PCT = 100.0  # 持仓市值超过总可投资金


def _signal(
    signal_id: str,
    category: SignalCategory,
    summary: str,
    severity: str = "info",
    **metrics,
) -> Signal:
    return Signal(
        id=signal_id,
        category=category,
        severity=severity,
        summary=summary,
        metrics={key: value for key, value in metrics.items() if value is not None},
    )


# ==================== 行情 ====================


def _market_signals(ctx: AdviceContext) -> list[Signal]:
    ind = ctx.indicators
    signals: list[Signal] = []

    # 用户配置的绝对低价安全线 —— 原来 alert_service 里唯一活着的规则，
    # 现在作为信号保留下来，避免改造后这条安全线失效。
    # 注意要尊重开关：设置页关掉它就该真的不生效。
    if (
        ctx.prefs.absolute_alert_enabled
        and ctx.prefs.absolute_low_price > 0
        and ind.current_price <= ctx.prefs.absolute_low_price
    ):
        signals.append(
            _signal(
                "absolute_low",
                SignalCategory.MARKET,
                f"现价 ¥{ind.current_price:.2f} 已跌破设定的安全线 "
                f"¥{ctx.prefs.absolute_low_price:.2f}",
                "critical",
                absolute_low_price=ctx.prefs.absolute_low_price,
            )
        )

    if ind.count_24h == 0:
        # 没有历史数据时不能假装能判断 —— 上层应当据此给出观望
        signals.append(
            _signal(
                "no_market_data",
                SignalCategory.MARKET,
                "缺少最近 24 小时的行情数据，暂时无法判断位置",
                "warning",
                current_price=ind.current_price,
            )
        )
        return signals

    if ind.pct_from_3m_low is not None and ind.pct_from_3m_low <= NEAR_LOW_TOLERANCE_PCT:
        signals.append(
            _signal(
                "long_term_low_3m",
                SignalCategory.MARKET,
                f"贴近近 90 日低点，仅高 {ind.pct_from_3m_low:.2f}%",
                "notice",
                min_3m=ind.min_3m,
                pct_from_3m_low=round(ind.pct_from_3m_low, 3),
            )
        )

    if ind.pct_from_6m_low is not None and ind.pct_from_6m_low <= NEAR_LOW_TOLERANCE_PCT:
        signals.append(
            _signal(
                "long_term_low_6m",
                SignalCategory.MARKET,
                f"贴近近 180 日低点，仅高 {ind.pct_from_6m_low:.2f}%",
                "notice",
                min_6m=ind.min_6m,
                pct_from_6m_low=round(ind.pct_from_6m_low, 3),
            )
        )

    if ind.pct_from_6m_low is not None and ind.pct_from_6m_low >= FAR_FROM_LOW_PCT:
        signals.append(
            _signal(
                "far_from_long_term_low",
                SignalCategory.MARKET,
                f"已高于近 180 日低点 {ind.pct_from_6m_low:.1f}%，不算便宜的位置",
                "info",
                min_6m=ind.min_6m,
                pct_from_6m_low=round(ind.pct_from_6m_low, 3),
            )
        )

    if ind.range_position_24h is not None:
        if ind.range_position_24h <= BOTTOM_RANGE_POSITION:
            signals.append(
                _signal(
                    "near_24h_low",
                    SignalCategory.MARKET,
                    f"处于近 24 小时区间下沿（{ind.range_position_24h * 100:.0f}% 位置）",
                    "info",
                    range_position_24h=round(ind.range_position_24h, 3),
                )
            )
        elif ind.range_position_24h >= TOP_RANGE_POSITION:
            signals.append(
                _signal(
                    "near_24h_high",
                    SignalCategory.MARKET,
                    f"处于近 24 小时区间上沿（{ind.range_position_24h * 100:.0f}% 位置）",
                    "info",
                    range_position_24h=round(ind.range_position_24h, 3),
                )
            )

    if ind.volatility_pct is not None and ind.volatility_pct >= HIGH_VOLATILITY_PCT:
        signals.append(
            _signal(
                "high_volatility",
                SignalCategory.MARKET,
                f"24 小时波动率 {ind.volatility_pct:.2f}%，高于 {HIGH_VOLATILITY_PCT}% 阈值",
                "notice",
                volatility_pct=round(ind.volatility_pct, 3),
            )
        )

    for label, direction in (("短期", ind.trend_6h_direction), ("中期", ind.trend_24h_direction)):
        if direction == "down":
            signals.append(
                _signal(
                    f"trend_{'short' if label == '短期' else 'mid'}_down",
                    SignalCategory.MARKET,
                    f"{label}趋势向下",
                    "info",
                    direction=direction,
                )
            )
        elif direction == "up":
            signals.append(
                _signal(
                    f"trend_{'short' if label == '短期' else 'mid'}_up",
                    SignalCategory.MARKET,
                    f"{label}趋势向上",
                    "info",
                    direction=direction,
                )
            )

    if ind.ma20:
        gap_pct = (ind.current_price - ind.ma20) / ind.ma20 * 100
        if abs(gap_pct) <= MA_GAP_PCT:
            signals.append(
                _signal(
                    "near_ma20",
                    SignalCategory.MARKET,
                    f"价格紧贴 20 周期均线（偏离 {gap_pct:+.2f}%）",
                    "info",
                    ma20=ind.ma20,
                    gap_pct=round(gap_pct, 3),
                )
            )
        else:
            signals.append(
                _signal(
                    "below_ma20" if gap_pct < 0 else "above_ma20",
                    SignalCategory.MARKET,
                    f"价格位于 20 周期均线{'下方' if gap_pct < 0 else '上方'} {abs(gap_pct):.2f}%",
                    "info",
                    ma20=ind.ma20,
                    gap_pct=round(gap_pct, 3),
                )
            )

    return signals


# ==================== 持仓 ====================


def _position_signals(ctx: AdviceContext) -> list[Signal]:
    position = ctx.position
    signals: list[Signal] = []

    if not ctx.has_position:
        signals.append(
            _signal(
                "no_position",
                SignalCategory.POSITION,
                "当前没有持仓",
                "info",
            )
        )
        return signals

    pnl_pct = position.unrealized_pnl_pct
    signals.append(
        _signal(
            "has_position",
            SignalCategory.POSITION,
            f"持仓 {position.total_grams}g，成本价 ¥{position.avg_cost:.2f}",
            "info",
            total_grams=position.total_grams,
            avg_cost=position.avg_cost,
        )
    )

    if pnl_pct is not None:
        if pnl_pct <= DEEP_LOSS_PCT:
            signals.append(
                _signal(
                    "deep_loss",
                    SignalCategory.POSITION,
                    f"浮亏 {pnl_pct:.2f}%，已超过 {DEEP_LOSS_PCT}% 阈值",
                    "critical",
                    unrealized_pnl=position.unrealized_pnl,
                    unrealized_pnl_pct=pnl_pct,
                )
            )
        elif pnl_pct <= LOSS_PCT:
            signals.append(
                _signal(
                    "in_loss",
                    SignalCategory.POSITION,
                    f"浮亏 {pnl_pct:.2f}%",
                    "notice",
                    unrealized_pnl=position.unrealized_pnl,
                    unrealized_pnl_pct=pnl_pct,
                )
            )
        elif pnl_pct >= PROFIT_PCT:
            signals.append(
                _signal(
                    "big_profit",
                    SignalCategory.POSITION,
                    f"浮盈 {pnl_pct:.2f}%，已超过 {PROFIT_PCT}% 阈值",
                    "notice",
                    unrealized_pnl=position.unrealized_pnl,
                    unrealized_pnl_pct=pnl_pct,
                )
            )
        else:
            signals.append(
                _signal(
                    "in_profit" if pnl_pct > 0 else "flat",
                    SignalCategory.POSITION,
                    f"浮动{'盈利' if pnl_pct > 0 else '接近持平'} {pnl_pct:+.2f}%",
                    "info",
                    unrealized_pnl_pct=pnl_pct,
                )
            )

    ratio = ctx.position_ratio_pct()
    if ratio is not None and ratio >= POSITION_RATIO_HIGH_PCT:
        signals.append(
            _signal(
                "position_ratio_high",
                SignalCategory.POSITION,
                f"持仓市值已占总可投资金的 {ratio:.0f}%，仓位偏重",
                "warning",
                position_ratio_pct=round(ratio, 2),
                total_investable=ctx.prefs.total_investable,
            )
        )

    return signals


# ==================== 计划 ====================


def _plan_signals(ctx: AdviceContext) -> list[Signal]:
    if not ctx.plans:
        return [
            _signal("no_plan", SignalCategory.PLAN, "没有进行中的购买计划", "info")
        ]

    signals: list[Signal] = []
    for state in ctx.plans:
        progress = state.progress
        prefix = f"计划 #{progress.plan_id}"

        if progress.status != "active":
            signals.append(
                _signal(
                    "plan_inactive",
                    SignalCategory.PLAN,
                    f"{prefix} 已{progress.status}，不参与执行判断",
                    "info",
                    plan_id=progress.plan_id,
                    status=progress.status,
                )
            )
            continue

        if not state.has_remaining:
            signals.append(
                _signal(
                    "plan_complete",
                    SignalCategory.PLAN,
                    f"{prefix} 已完成（{progress.filled_grams}/{progress.target_grams}g）",
                    "info",
                    plan_id=progress.plan_id,
                    progress_pct=progress.progress_pct,
                )
            )
            continue

        signals.append(
            _signal(
                "plan_active",
                SignalCategory.PLAN,
                f"{prefix} 进行中，已买 {progress.filled_grams}/{progress.target_grams}g"
                f"（{progress.progress_pct:.0f}%）",
                "info",
                plan_id=progress.plan_id,
                filled_grams=progress.filled_grams,
                remaining_grams=progress.remaining_grams,
                progress_pct=progress.progress_pct,
            )
        )

        if state.due_by_interval() or state.due_by_drop(ctx.current_price):
            reason = (
                f"距上次买入已 {state.days_since_last_lot} 天"
                if state.trigger_policy.get("type") == "interval"
                else f"现价较上次买入价 ¥{state.last_lot_price:.2f} 已回落"
            )
            if progress.filled_tranches == 0:
                reason = "尚未开始建仓"
            signals.append(
                _signal(
                    "plan_due",
                    SignalCategory.PLAN,
                    f"{prefix} 本批已到点（{reason}）",
                    "notice",
                    plan_id=progress.plan_id,
                    trigger_policy=state.trigger_policy,
                    days_since_last_lot=state.days_since_last_lot,
                    last_lot_price=state.last_lot_price,
                )
            )
        else:
            signals.append(
                _signal(
                    "plan_not_due",
                    SignalCategory.PLAN,
                    f"{prefix} 本批尚未到点",
                    "info",
                    plan_id=progress.plan_id,
                    trigger_policy=state.trigger_policy,
                    days_since_last_lot=state.days_since_last_lot,
                )
            )

    return signals


# ==================== 入口 ====================


def evaluate(ctx: AdviceContext) -> list[Signal]:
    """评估全部信号（顺序稳定，便于测试与展示）"""
    return [*_market_signals(ctx), *_position_signals(ctx), *_plan_signals(ctx)]


def has(signals: list[Signal], signal_id: str) -> bool:
    return any(signal.id == signal_id for signal in signals)


def get(signals: list[Signal], signal_id: str) -> Signal | None:
    for signal in signals:
        if signal.id == signal_id:
            return signal
    return None
