"""通知渠道的基础设施。

所有外发消息统一为 `NotificationData`，按 `kind` 区分语义：
建议 / 复盘走 `advice` 载荷，其余类型（波动提醒、每日摘要、节后缺口…）
走 `fields` 通用字段，模板按 kind 注册渲染器 —— 新增消息类型无需改渠道。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ---- 消息类型 ----
KIND_ADVICE = "advice"  # 买入建议
KIND_REVIEW = "review"  # 买入后 T+n 复盘（渲染同建议）
KIND_VOLATILITY = "volatility"  # 价格波动事件
KIND_DIGEST = "digest"  # 每日行情摘要
KIND_REOPEN_GAP = "reopen_gap"  # 节后开盘缺口预告

#: 建议类消息（渲染走建议模板，需要 advice 载荷）
ADVICE_KINDS = (KIND_ADVICE, KIND_REVIEW)


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
class NotificationData:
    """通知载荷 —— 所有外发消息的统一载体。

    `alert_level` 对应通知日志列 `notification_send_logs.alert_level`，前端统计页按它上色。
    非 advice 类消息用 `fields` 携带已格式化的字段（键为中文标签，值为展示文本），
    `summary` 用于投递日志的一行摘要。
    """

    kind: str = KIND_ADVICE
    symbol: str = ""
    symbol_name: str = ""
    current_price: float = 0.0
    advice: AdvicePayload | None = None
    fields: dict[str, str] = field(default_factory=dict)
    extra_info: dict | None = None
    #: None = 未指定 —— 非建议类消息在 `NotificationService.send()` 分发时
    #: 降为 info；显式指定（如波动提醒 warning/critical）则原样透传
    alert_level: str | None = None
    summary: str = ""


#: 兼容别名：阶段 A 之前所有消息都是建议，旧代码与测试按此名引用
AdviceData = NotificationData


class BaseNotificationChannel(ABC):
    @property
    @abstractmethod
    def channel_type(self) -> str: ...

    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    def send(self, data: NotificationData, config: dict) -> ChannelResult: ...

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
