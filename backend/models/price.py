from datetime import datetime

from pydantic import BaseModel, Field


class PriceRecordBase(BaseModel):
    """价格记录基础字段"""

    symbol: str = Field(..., description="品种代码", examples=["Au(T+D)", "hf_XAU"])
    price: float = Field(..., gt=0, description="价格")


class PriceRecordCreate(PriceRecordBase):
    """创建价格记录 — POST 请求体"""

    timestamp: datetime | None = Field(
        default=None, description="记录时间，不传则使用当前时间"
    )


class PriceRecordResponse(PriceRecordBase):
    """价格记录 — GET 返回体"""

    id: int = Field(..., description="记录 ID")
    timestamp: datetime = Field(..., description="记录时间")

    model_config = {"from_attributes": True}


# ==================== 统计类 ====================


class PriceStatistics(BaseModel):
    """价格统计"""

    min: float = Field(..., description="最低价")
    max: float = Field(..., description="最高价")
    avg: float = Field(..., description="均价")
    count: int = Field(..., description="数据量")
    std: float = Field(..., description="标准差")


class PriceChartPoint(BaseModel):
    """走势图数据点"""

    timestamp: datetime = Field(..., description="记录时间")
    price: float = Field(..., description="价格")


class PriceTrend(BaseModel):
    """价格趋势"""

    slope: float = Field(..., description="斜率")
    direction: str = Field(..., description="趋势方向：up/down/stable")


class PriceSnapshotResponse(BaseModel):
    """价格快照 — 聚合视图"""

    symbol: str = Field(..., description="品种代码")
    current_price: float = Field(..., description="当前价格")
    statistics_24h: PriceStatistics | None = Field(
        default=None, description="24小时统计"
    )
    trend_6h: PriceTrend | None = Field(default=None, description="6小时趋势")
    trend_24h: PriceTrend | None = Field(default=None, description="24小时趋势")
    ma_5: float | None = Field(default=None, description="5周期均线")
    ma_10: float | None = Field(default=None, description="10周期均线")
    ma_20: float | None = Field(default=None, description="20周期均线")
    min_3m: float | None = Field(default=None, description="近90日最低")
    min_6m: float | None = Field(default=None, description="近180日最低")
    recent_prices: list[float] = Field(default_factory=list, description="最近5个价格")


# ==================== 仪表盘 ====================


class SymbolDashboardItem(BaseModel):
    """各品种仪表盘项"""

    symbol: str = Field(..., description="品种代码")
    name: str = Field(..., description="品种中文名")
    count: int = Field(..., description="该品种总记录数")
    latest_price: float | None = Field(default=None, description="最新价格")
    latest_time: datetime | None = Field(default=None, description="最新记录时间")
    today_high: float | None = Field(default=None, description="范围内最高价")
    today_low: float | None = Field(default=None, description="范围内最低价")
    data_freshness_seconds: int | None = Field(
        default=None, description="距最新数据秒数"
    )


class PriceDashboardStats(BaseModel):
    """仪表盘 — 价格统计"""

    total_records: int = Field(default=0, description="数据库总记录数")
    new_records: int = Field(default=0, description="时间范围内新增记录数")
    symbols: list[SymbolDashboardItem] = Field(
        default_factory=list, description="各品种统计"
    )


class AiDashboardStats(BaseModel):
    """仪表盘 — AI 统计"""

    total_calls: int = Field(default=0, description="AI 调用总次数")
    success_count: int = Field(default=0, description="成功次数")
    failure_count: int = Field(default=0, description="失败次数")
    success_rate: float = Field(default=0.0, description="成功率(%)")
    cache_hit_count: int = Field(default=0, description="缓存命中次数")
    total_tokens: int = Field(default=0, description="消耗 Token 总数")
    last_success_time: str | None = Field(default=None, description="最近一次成功时间")


class NotificationDashboardStats(BaseModel):
    """仪表盘 — 通知统计"""

    total_sends: int = Field(default=0, description="通知发送总次数")
    success_count: int = Field(default=0, description="成功次数")
    failure_count: int = Field(default=0, description="失败次数")
    success_rate: float = Field(default=0.0, description="成功率(%)")


class DashboardResponse(BaseModel):
    """仪表盘总览 — 系统统一概览"""

    start_date: str = Field(default="", description="统计起始日期")
    end_date: str = Field(default="", description="统计结束日期")
    price: PriceDashboardStats = Field(
        default_factory=PriceDashboardStats, description="价格统计"
    )
    ai: AiDashboardStats = Field(
        default_factory=AiDashboardStats, description="AI 统计"
    )
    notification: NotificationDashboardStats = Field(
        default_factory=NotificationDashboardStats, description="通知统计"
    )
    active_symbols_count: int = Field(default=0, description="监控品种数")
    monitored_symbols: list[str] = Field(
        default_factory=list, description="监控品种列表"
    )
    main_symbol: str = Field(default="", description="主监控品种")
