from datetime import datetime

from pydantic import BaseModel, Field


class ExchangeRateRecord(BaseModel):
    """汇率历史记录"""

    id: int
    rate: float
    timestamp: datetime


class ExchangeRateStatistics(BaseModel):
    """汇率统计"""

    min: float = Field(..., description="最低汇率")
    max: float = Field(..., description="最高汇率")
    avg: float = Field(..., description="均价")
    count: int = Field(..., description="数据量")
    std: float = Field(..., description="标准差")


class ExchangeRateChartPoint(BaseModel):
    """走势图数据点"""

    timestamp: datetime = Field(..., description="记录时间")
    rate: float = Field(..., description="汇率")


class ExchangeRateTrend(BaseModel):
    """汇率趋势"""

    slope: float = Field(..., description="斜率")
    direction: str = Field(..., description="趋势方向：up/down/stable")


class ExchangeRateDashboardItem(BaseModel):
    """汇率仪表盘项"""

    record_count: int = Field(default=0, description="总记录数")
    latest_rate: float | None = Field(default=None, description="最新汇率")
    latest_time: datetime | None = Field(default=None, description="最新记录时间")
    today_high: float | None = Field(default=None, description="今日最高")
    today_low: float | None = Field(default=None, description="今日最低")
    data_freshness_seconds: int | None = Field(
        default=None, description="距最新数据秒数"
    )
