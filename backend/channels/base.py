"""通知渠道的基础设施。

**报警路径已在阶段 4 的清理中移除**（见 `docs/refactor-plan.md` §18）：现在所有外发
消息都是「建议」。因此载荷直接叫 `AdviceData`，字段也不再区分报警/建议两种形态。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ChannelResult:
    success: bool
    channel_type: str
    message: str = ""
    latency_ms: float = 0.0
    error_type: str = ""
    error_detail: str = ""


@dataclass
class AdvicePayload:
    """建议语义的载荷 —— 渠道渲染所需的一切"""

    action: str
    rationale: str = ""
    target_grams: float | None = None
    price_band_low: float | None = None
    price_band_high: float | None = None
    confidence: float = 0.5
    signals: list[str] = field(default_factory=list)
    #: 持仓上下文（没有持仓时为 None）
    total_grams: float | None = None
    avg_cost: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    advice_id: int | None = None
    #: 复盘类建议针对的那笔买入（None 表示不是复盘）
    subject_lot_id: int | None = None
    review_horizon: int | None = None


@dataclass
class AdviceData:
    """通知载荷 —— 建议类消息的统一载体。

    `alert_level` 这个名字保留自原来的通知日志列（`notification_send_logs.alert_level`），
    前端的通知统计页仍在按它上色，改名的收益不抵迁移成本。
    """

    symbol: str
    symbol_name: str
    current_price: float
    advice: AdvicePayload
    extra_info: dict | None = None
    alert_level: str = "warning"


class BaseNotificationChannel(ABC):
    @property
    @abstractmethod
    def channel_type(self) -> str: ...

    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    def send(self, data: AdviceData, config: dict) -> ChannelResult: ...

    def validate_config(self, config: dict) -> bool:
        return True


def classify_error(error_detail: str) -> str:
    if not error_detail:
        return ""
    detail_lower = error_detail.lower()
    if any(kw in detail_lower for kw in ("timeout", "timed out", "connect")):
        return "network_timeout"
    if any(kw in detail_lower for kw in ("auth", "login", "535", "401", "403")):
        return "auth_failed"
    if any(
        kw in detail_lower for kw in ("未配置", "not configured", "missing", "empty")
    ):
        return "config_missing"
    if any(kw in detail_lower for kw in ("rate limit", "freq", "45009", "429")):
        return "rate_limited"
    if any(kw in detail_lower for kw in ("errcode", "errmsg", "status_code", "4", "5")):
        return "api_error"
    return "unknown"
