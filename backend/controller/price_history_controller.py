from fastapi import APIRouter, Query

from models.price import (
    DashboardResponse,
    PriceChartPoint,
    PriceRecordResponse,
    PriceStatistics,
    PriceTrend,
)
from models.response import ApiResponse
from service.price_history_service import PriceHistoryService
from service.system_settings_service import SystemSettingsService

router = APIRouter(prefix="/prices", tags=["金价历史"])
service = PriceHistoryService()


def _default_symbol() -> str:
    monitor_config = SystemSettingsService().get_monitor_config()
    return monitor_config.get("main_symbol", "gds_AUTD")


# ==================== 记录数 ====================


@router.get("/count", response_model=ApiResponse[int])
def get_record_count(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
):
    return ApiResponse.ok(service.get_record_count(symbol))


# ==================== 统计信息 ====================


@router.get("/statistics", response_model=ApiResponse[PriceStatistics])
def get_statistics(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    hours: float = Query(default=24, ge=1, description="统计窗口（小时）"),
):
    result = service.get_statistics(symbol, hours)
    if not result:
        return ApiResponse.fail(f"品种 [{symbol}] 暂无价格数据", code=404)
    return ApiResponse.ok(result)


# ==================== 趋势 ====================


@router.get("/trend", response_model=ApiResponse[PriceTrend])
def get_trend(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    hours: float = Query(default=6, ge=1, description="趋势窗口（小时）"),
):
    return ApiResponse.ok(service.get_trend(symbol, hours))


# ==================== 仪表盘 ====================


@router.get("/dashboard", response_model=ApiResponse[DashboardResponse])
def get_dashboard():
    return ApiResponse.ok(service.get_dashboard())


# ==================== 图表数据 ====================


@router.get("/chart", response_model=ApiResponse[list[PriceChartPoint]])
def get_chart_data(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    hours: float = Query(
        default=24,
        ge=1,
        le=8760,
        description="图表时间范围（小时，最长365天 | 720=30天 2160=90天 4380=半年 8760=1年）",
    ),
):
    return ApiResponse.ok(service.get_chart_data(symbol, hours))


# ==================== 最近记录 ====================


@router.get("/recent", response_model=ApiResponse[list[PriceRecordResponse]])
def get_recent_records(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
):
    return ApiResponse.ok(service.get_recent_records(symbol, limit))
