"""建议触发器 —— 迁移自 `MonitorService._advise` 的评估与推送节流逻辑。

职责边界：触发器只产出「候选事件 / 抑制记录」；
终审闸门、落库、投递由 `MonitorService` 统一执行 —— 行为与迁移前一致。
"""

# 延迟导入以避免触发器包与建议引擎的循环依赖
from service.triggers.base import (
    ADVICE_COOLDOWN_MINUTES,
    KIND_ADVICE,
    NotificationEvent,
    Suppression,
    TickContext,
    Trigger,
    TriggerOutcome,
)
from utils.due_timer import DueTimer
from utils.logger import get_logger
from utils.market_session import SendPolicy

logger = get_logger("AdviceTrigger")

#: 建议动作 → 优先级（与 models.advice.ACTION_URGENCY 同源，延迟导入使用）


class AdviceTrigger(Trigger):
    def __init__(self, engine, interval_seconds: float = 0.0) -> None:
        self.engine = engine
        self._timer = DueTimer("建议评估", interval_seconds)

    @property
    def name(self) -> str:
        return "advice"

    def set_interval(self, seconds: float) -> None:
        """热更新评估间隔（配置变更时调用，语义与原 `_advice_timer` 一致）"""
        self._timer.set_interval(seconds)

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        if not self._timer.is_due(tick.at):
            return TriggerOutcome()
        self._timer.mark(tick.at)

        computed = self.engine.compute(
            tick.main_symbol,
            tick.market_price,
            tick.london_cny,
            tick.london_usd,
            market_symbol=tick.market_symbol,
        )
        action = computed.draft.action.value
        logger.info(
            f"建议评估：{action}（{computed.draft.kind.value}）"
            f"置信度 {computed.draft.confidence}"
        )

        # 推送节流：动作变化，或价格偏离上次推送超过阈值
        # （基准随口径走：休市期比较的是国际金价格，不再是冻结的 SGE 价格）
        should_push, _reason = self._should_push(tick, computed)
        if not should_push:
            return TriggerOutcome(
                suppressed=[
                    Suppression(
                        source="建议",
                        reason="duplicate",
                        detail="动作与上次相同，且价格未明显变动",
                        computed=computed,
                    )
                ]
            )

        from models.advice import ACTION_URGENCY

        urgency = ACTION_URGENCY.get(action, "low")
        extra_info: dict = {}
        if tick.london_cny is not None:
            extra_info["london_gold_usd"] = tick.london_usd
            extra_info["london_gold_cny"] = tick.london_cny
        if computed.model_info:
            extra_info["ai_model_info"] = computed.model_info
        if tick.valuation_note:
            extra_info["valuation_note"] = tick.valuation_note

        return TriggerOutcome(
            events=[
                NotificationEvent(
                    kind=KIND_ADVICE,
                    symbol=tick.main_symbol,
                    dedup_key=f"{tick.main_symbol}#advice#{action}",
                    urgency=urgency,
                    cooldown_minutes=ADVICE_COOLDOWN_MINUTES,
                    price_basis=tick.market_price,
                    current_price=tick.market_price,
                    computed=computed,
                    extra_info=extra_info,
                )
            ]
        )

    def _should_push(self, tick: TickContext, computed) -> tuple[bool, str]:
        """只在「动作变了」或「价格明显变了」时才推送，避免刷屏。

        用数据库里的上一条已推送建议做比较（而不是内存），这样重启后不会立刻重复推。
        """
        last = self.engine.last_pushed(tick.main_symbol)
        if last is None:
            return True, ""
        if last.action.value != computed.draft.action.value:
            return True, ""

        threshold = self.engine.price_move_trigger_pct()
        if threshold > 0 and last.price_at_advice:
            move = (
                abs(tick.market_price - last.price_at_advice)
                / last.price_at_advice
                * 100
            )
            if move >= threshold:
                return True, ""
        return False, "duplicate"


def market_view_of(tick: TickContext) -> str | None:
    """日志辅助：当前口径品种描述"""
    if tick.market_symbol and tick.decision.policy is SendPolicy.INTL_ONLY:
        return tick.market_symbol
    return None
