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
    hours: float | None = Query(
        default=None, ge=1, description="统计窗口（小时），优先于日期范围"
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    result = service.get_statistics(symbol, hours, start_date, end_date)
    if not result:
        return ApiResponse.fail(f"品种 [{symbol}] 暂无价格数据", code=404)
    return ApiResponse.ok(result)


# ==================== 趋势 ====================


@router.get("/trend", response_model=ApiResponse[PriceTrend])
def get_trend(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    hours: float | None = Query(
        default=None, ge=1, description="趋势窗口（小时），优先于日期范围"
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    return ApiResponse.ok(service.get_trend(symbol, hours, start_date, end_date))


# ==================== 仪表盘 ====================


@router.get("/dashboard", response_model=ApiResponse[DashboardResponse])
def get_dashboard(
    start_date: str | None = Query(
        default=None, description="起始日期（YYYY-MM-DD），默认今天"
    ),
    end_date: str | None = Query(
        default=None, description="结束日期（YYYY-MM-DD），默认今天"
    ),
    hours: int | None = Query(
        default=None, ge=1, description="最近N小时（优先于日期范围）"
    ),
):
    return ApiResponse.ok(service.get_dashboard(start_date, end_date, hours))


# ==================== 图表数据 ====================


@router.get("/chart", response_model=ApiResponse[list[PriceChartPoint]])
def get_chart_data(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    hours: float | None = Query(
        default=None,
        ge=1,
        le=8760,
        description="图表时间范围（小时），优先于日期范围",
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    return ApiResponse.ok(service.get_chart_data(symbol, hours, start_date, end_date))


# ==================== 最近记录 ====================


@router.get("/recent", response_model=ApiResponse[list[PriceRecordResponse]])
def get_recent_records(
    symbol: str = Query(default_factory=_default_symbol, description="品种代码"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
):
    return ApiResponse.ok(service.get_recent_records(symbol, limit))
