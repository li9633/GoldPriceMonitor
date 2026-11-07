"""触发器框架 —— 通知由「事件」产生，而非「周期评估 + 事后抑制」。

分层（notification-refactor-plan §3/§4.2）：

- `Trigger.evaluate(tick) -> TriggerOutcome`：判断本 tick 是否产生了值得通知的事件；
- `NotificationEvent`：候选通知，携带去重键、优先级、冷却参数与价格基准；
- `MonitorService` 负责统一执行：终审闸门（SendGate.review）→ 落库 → 投递。

两类事件载体：
- `computed` 非空 —— 建议类（advice/review）：由 MonitorService 落库并走 send_advice；
- `notification` 非空 —— 非建议类（volatility/digest/reopen_gap）：直接投递，不进 advice_records。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from channels.base import KIND_ADVICE, KIND_REVIEW
from service.advice.advice_engine import ComputedAdvice
from service.send_gate import GateDecision

#: 建议类事件的默认冷却（与 SendDeduplicator 原默认一致，保持行为不变）
ADVICE_COOLDOWN_MINUTES = 10.0


@dataclass
class TickContext:
    """一个巡检周期内触发器评估所需的全部输入"""

    at: datetime
    decision: GateDecision
    prices_data: dict
    main_symbol: str
    #: 行情口径：INTL_ONLY 时为 "hf_XAU"，其余与 main_symbol 相同
    market_symbol: str | None
    #: 口径价格：INTL_ONLY 时为国际金折算价，否则为主品种现价
    market_price: float
    london_cny: float | None
    london_usd: float | None
    #: 估值口径说明（INTL_ONLY 时非空，渲染进消息）
    valuation_note: str = ""


@dataclass
class Suppression:
    """被抑制的通知。`computed` 为 None 时表示「刻意不落库」（如复盘会重试）"""

    source: str
    reason: str
    detail: str
    computed: ComputedAdvice | None = None


@dataclass
class NotificationEvent:
    """候选通知 —— 终审闸门的输入"""

    kind: str
    symbol: str
    dedup_key: str
    urgency: str
    cooldown_minutes: float
    #: 去重比较用的价格基准（随口径走）
    price_basis: float
    current_price: float
    summary: str = ""
    #: 建议类：待落库的建议（MonitorService save 后走 send_advice）
    computed: ComputedAdvice | None = None
    extra_info: dict = field(default_factory=dict)
    #: 非建议类：直接投递的载荷（不落 advice_records）
    notification: object | None = None
    #: 被终审闸门拦下时是否把建议落库为 suppressed。
    #: 复盘为 False（刻意不落库，追补窗口内会重试）；建议为 True。
    save_suppressed: bool = True


@dataclass
class TriggerOutcome:
    events: list[NotificationEvent] = field(default_factory=list)
    suppressed: list[Suppression] = field(default_factory=list)


class Trigger(ABC):
    """通知触发器基类：谁动了才发，而不是到点就评"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, tick: TickContext) -> TriggerOutcome: ...


class TriggerRegistry:
    """按顺序评估所有触发器，汇总事件与抑制"""

    def __init__(self, triggers: list[Trigger] | None = None) -> None:
        self._triggers: list[Trigger] = list(triggers or [])

    def register(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    @property
    def triggers(self) -> list[Trigger]:
        return list(self._triggers)

    def evaluate_all(self, tick: TickContext) -> TriggerOutcome:
        outcome = TriggerOutcome()
        for trigger in self._triggers:
            try:
                result = trigger.evaluate(tick)
            except Exception as exc:  # noqa: BLE001
                from utils.logger import get_logger

                get_logger("TriggerRegistry").error(
                    f"触发器 {trigger.name} 评估失败：{exc}", exc_info=exc
                )
                continue
            outcome.events.extend(result.events)
            outcome.suppressed.extend(result.suppressed)
        return outcome


__all__ = [
    "ADVICE_COOLDOWN_MINUTES",
    "KIND_ADVICE",
    "KIND_REVIEW",
    "NotificationEvent",
    "Suppression",
    "TickContext",
    "Trigger",
    "TriggerOutcome",
    "TriggerRegistry",
]
