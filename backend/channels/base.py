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
class AlertData:
    symbol: str
    symbol_name: str
    current_price: float
    alert_messages: list[str]
    suggestions: list[str] = field(default_factory=list)
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
    def send(self, alert_data: AlertData, config: dict) -> ChannelResult: ...

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
