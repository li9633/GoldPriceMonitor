from pydantic import BaseModel


class NotifyStatsOverview(BaseModel):
    today_total: int = 0
    today_success: int = 0
    today_failure: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_all: int = 0


class FailureReasonItem(BaseModel):
    error_type: str
    error_type_label: str
    fail_count: int
    percentage: float = 0.0
    examples: str = ""


class ChannelStatsItem(BaseModel):
    channel_type: str
    channel_name: str
    total: int = 0
    success_count: int = 0
    fail_count: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0


class DailyTrendItem(BaseModel):
    date: str
    total: int = 0
    success_count: int = 0
    fail_count: int = 0


class NotifyLogItem(BaseModel):
    id: int
    alert_level: str
    symbol: str
    symbol_name: str
    current_price: float | None = None
    alert_summary: str = ""
    channel_type: str
    channel_name: str
    chain_id: str = ""
    chain_position: int = 0
    chain_total: int = 1
    success: bool
    latency_ms: float | None = None
    error_type: str = ""
    error_reason: str = ""
    created_at: str = ""
