from pydantic import BaseModel, Field


class TopModelItem(BaseModel):
    provider: str
    model: str
    count: int


class TopProviderItem(BaseModel):
    provider: str
    count: int


class FailureReasonItem(BaseModel):
    reason: str
    count: int


class HourlyItem(BaseModel):
    hour: str
    count: int


class ModelRankingItem(BaseModel):
    provider: str
    model: str
    total: int
    success_rate: float
    avg_latency: float


class ProviderRankingItem(BaseModel):
    provider: str
    total: int
    success_rate: float
    avg_latency: float


class ProviderFailureItem(BaseModel):
    provider: str
    count: int


class AiStatsOverview(BaseModel):
    today_total: int = Field(..., description="今日调用总次数")
    today_success: int = Field(..., description="今日成功次数")
    today_failure: int = Field(..., description="今日失败次数")
    success_rate: float = Field(..., description="今日成功率(%)")
    failure_rate: float = Field(..., description="今日失败率(%)")
    consecutive_failures: int = Field(..., description="当前连续失败次数")
    last_success_time: str | None = Field(None, description="最后一次成功时间")
    avg_latency_ms: float = Field(..., description="今日平均延迟(ms)")
    p50_latency_ms: float = Field(..., description="P50延迟(ms)")
    p95_latency_ms: float = Field(..., description="P95延迟(ms)")
    p99_latency_ms: float = Field(..., description="P99延迟(ms)")
    timeout_rate: float = Field(..., description="超时占比(%)")
    total_all: int = Field(..., description="累计总调用次数")
    cache_hit_count: int = Field(..., description="今日缓存命中次数")
    cache_hit_rate: float = Field(..., description="今日缓存命中率(%)")
    top_model: TopModelItem | None = None
    top_provider: TopProviderItem | None = None
    top_failures: list[FailureReasonItem] = Field(default_factory=list)
    hourly_distribution: list[HourlyItem] = Field(default_factory=list)
    model_ranking: list[ModelRankingItem] = Field(default_factory=list)
    provider_ranking: list[ProviderRankingItem] = Field(default_factory=list)
    provider_failures: list[ProviderFailureItem] = Field(default_factory=list)


class DailyTrendItem(BaseModel):
    date: str
    total: int
    success_count: int
    success_rate: float
    avg_latency: float


class AiCallLogItem(BaseModel):
    id: int
    provider_name: str
    model_name: str
    call_time: str
    success: bool
    latency_ms: int | None
    error_reason: str | None
    from_cache: bool
    triggered_alerts: str | None
