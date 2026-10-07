"""消息发送闸门 —— 时段静默 + 去重。

两道闸门，位于两个不同的决策点上：

1. **时段闸门**（`policy_decision`，调用 AI **之前**）：策略为 `SILENT` 时直接返回，
   既不发消息，也不花 AI 的钱。
2. **终审闸门**（`review`，发送**之前**）：`LOW_FREQ` 只放行高优先级；再叠加一层与
   时段无关的去重 —— 同一类消息在冷却期内不重复发送，除非价格明显变动。

去重参数：10 分钟冷却 / 0.3% 价格变动。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from utils.logger import get_logger
from utils.market_session import (
    SendPolicy,
    Session,
    describe,
    intl_session,
    policy_for,
    sge_session,
)
from utils.time_utils import now

logger = get_logger("SendGate")

#: 去重表最多保留的键数量，超出后按冷却期清理，避免长期运行下缓慢增长
_MAX_DEDUP_KEYS = 64


@dataclass(frozen=True)
class GateDecision:
    """时段闸门的结论（AI 调用之前）"""

    policy: SendPolicy
    sge: Session
    intl: Session
    allowed: bool
    reason: str
    detail: str

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class SendDecision:
    """终审闸门的结论（发送之前）"""

    allowed: bool
    reason: str
    detail: str

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class _SentRecord:
    at: datetime
    price: float


class SendDeduplicator:
    """同一类消息在冷却期内不重复发送，价格明显变动时放行。"""

    def __init__(
        self,
        cooldown_minutes: float = 10.0,
        price_change_threshold: float = 0.003,
    ) -> None:
        self.cooldown_minutes = cooldown_minutes
        self.price_change_threshold = price_change_threshold
        self._sent: dict[str, _SentRecord] = {}

    def check(
        self,
        key: str,
        price: float,
        at: datetime | None = None,
        cooldown_minutes: float | None = None,
    ) -> SendDecision:
        """判断是否可以发送；放行时会记录本次发送。

        `cooldown_minutes` 为空时使用实例默认值 —— 事件可携带自己的冷却参数。
        """
        at = at or now()
        cooldown = (
            self.cooldown_minutes if cooldown_minutes is None else cooldown_minutes
        )
        record = self._sent.get(key)
        if record is not None:
            elapsed_minutes = (at - record.at).total_seconds() / 60
            if elapsed_minutes < cooldown:
                change = (
                    abs(price - record.price) / record.price
                    if record.price > 0
                    else 0.0
                )
                if change < self.price_change_threshold:
                    return SendDecision(
                        False,
                        "duplicate",
                        f"{elapsed_minutes:.1f} 分钟前已发送同类消息，"
                        f"价格变动 {change * 100:.2f}% 未超过 "
                        f"{self.price_change_threshold * 100:.2f}%，已跳过",
                    )

        self._prune(at, cooldown)
        self._sent[key] = _SentRecord(at=at, price=price)
        return SendDecision(True, "", "")

    def reset(self) -> None:
        self._sent.clear()

    def _prune(self, at: datetime, cooldown_minutes: float | None = None) -> None:
        if len(self._sent) < _MAX_DEDUP_KEYS:
            return
        cooldown = (
            self.cooldown_minutes if cooldown_minutes is None else cooldown_minutes
        )
        cutoff = at - timedelta(minutes=max(cooldown * 6, 60.0))
        for key in [k for k, r in self._sent.items() if r.at < cutoff]:
            del self._sent[key]


class SendGate:
    """时段策略 + 去重的统一入口"""

    def __init__(self, deduplicator: SendDeduplicator | None = None) -> None:
        self.dedup = deduplicator or SendDeduplicator()

    def policy_decision(self, at: datetime | None = None) -> GateDecision:
        """时段闸门：在调用 AI 之前判断该时段要不要发消息"""
        at = at or now()
        sge = sge_session(at)
        intl = intl_session(at)
        policy = policy_for(sge, intl)
        allowed = policy is not SendPolicy.SILENT
        return GateDecision(
            policy=policy,
            sge=sge,
            intl=intl,
            allowed=allowed,
            reason="" if allowed else "silent",
            detail=describe(sge, intl),
        )

    def review(
        self,
        decision: GateDecision,
        *,
        key: str,
        price: float,
        urgency: str | None = None,
        cooldown_minutes: float | None = None,
        at: datetime | None = None,
    ) -> SendDecision:
        """终审闸门：发送前的优先级过滤与去重。

        `cooldown_minutes` 由事件声明（默认沿用去重器实例值）。
        """
        if not decision.allowed:
            return SendDecision(False, decision.reason or "silent", decision.detail)

        if decision.policy is SendPolicy.LOW_FREQ and urgency != "high":
            return SendDecision(
                False,
                "low_priority",
                f"国际金休市、SGE 开市，仅放行高优先级；本次优先级为 "
                f"{urgency or '未知'}，已跳过",
            )

        return self.dedup.check(key, price, at, cooldown_minutes)
