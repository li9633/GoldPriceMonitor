from fastapi import APIRouter, Query

from models.exchange_rate import (
    ExchangeRateChartPoint,
    ExchangeRateDashboardItem,
    ExchangeRateStatistics,
    ExchangeRateTrend,
)
from models.response import ApiResponse
from service.exchange_rate_service import ExchangeRateService

router = APIRouter(prefix="/exchange-rate", tags=["美元汇率"])
service = ExchangeRateService()


@router.get("/count", response_model=ApiResponse[int])
def get_record_count():
    return ApiResponse.ok(service.get_record_count())


@router.get("/statistics", response_model=ApiResponse[ExchangeRateStatistics])
def get_statistics(
    hours: float | None = Query(
        default=None, ge=1, description="统计窗口（小时），优先于日期范围"
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    result = service.get_statistics(hours, start_date, end_date)
    if not result:
        return ApiResponse.fail("暂无汇率数据", code=404)
    return ApiResponse.ok(result)


@router.get("/trend", response_model=ApiResponse[ExchangeRateTrend])
def get_trend(
    hours: float | None = Query(
        default=None, ge=1, description="趋势窗口（小时），优先于日期范围"
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    return ApiResponse.ok(service.get_trend(hours, start_date, end_date))


@router.get("/dashboard", response_model=ApiResponse[ExchangeRateDashboardItem])
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


@router.get("/chart", response_model=ApiResponse[list[ExchangeRateChartPoint]])
def get_chart_data(
    hours: float | None = Query(
        default=None,
        ge=1,
        le=8760,
        description="图表时间范围（小时），优先于日期范围",
    ),
    start_date: str | None = Query(default=None, description="起始日期（YYYY-MM-DD）"),
    end_date: str | None = Query(default=None, description="结束日期（YYYY-MM-DD）"),
):
    return ApiResponse.ok(service.get_chart_data(hours, start_date, end_date))


@router.get("/recent", response_model=ApiResponse[list[ExchangeRateChartPoint]])
def get_recent_records(
    hours: float = Query(default=24, ge=1, le=720, description="查询时间范围（小时）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
):
    return ApiResponse.ok(service.get_recent_records(hours, limit))
