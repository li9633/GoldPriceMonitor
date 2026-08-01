from fastapi import APIRouter, Query

from models.notification_stats import (
    ChannelStatsItem,
    DailyTrendItem,
    FailureReasonItem,
    NotifyLogItem,
    NotifyStatsOverview,
)
from models.response import ApiResponse, PageResponse
from service.notification_stats_service import NotificationStatsService

router = APIRouter(prefix="/notification-stats", tags=["通知统计"])
service = NotificationStatsService()

_STATS_RANGE_DESC = "最近N小时（优先级最高，覆盖日期参数）。例如 1、6、12、24"
_START_DATE_DESC = "起始日期（YYYY-MM-DD），默认今天"
_END_DATE_DESC = "结束日期（YYYY-MM-DD），默认今天"


@router.get("/overview", response_model=ApiResponse[NotifyStatsOverview])
def get_overview(
    hours: int | None = Query(None, ge=1, description=_STATS_RANGE_DESC),
    start_date: str | None = Query(None, description=_START_DATE_DESC),
    end_date: str | None = Query(None, description=_END_DATE_DESC),
):
    return ApiResponse.ok(service.get_overview(hours, start_date, end_date))


@router.get("/top-failures", response_model=ApiResponse[list[FailureReasonItem]])
def get_top_failures(
    hours: int | None = Query(None, ge=1, description=_STATS_RANGE_DESC),
    start_date: str | None = Query(None, description=_START_DATE_DESC),
    end_date: str | None = Query(None, description=_END_DATE_DESC),
):
    return ApiResponse.ok(service.get_top_failures(hours, start_date, end_date))


@router.get("/by-channel", response_model=ApiResponse[list[ChannelStatsItem]])
def get_channel_stats(
    hours: int | None = Query(None, ge=1, description=_STATS_RANGE_DESC),
    start_date: str | None = Query(None, description=_START_DATE_DESC),
    end_date: str | None = Query(None, description=_END_DATE_DESC),
):
    return ApiResponse.ok(service.get_channel_stats(hours, start_date, end_date))


@router.get("/daily-trend", response_model=ApiResponse[list[DailyTrendItem]])
def get_daily_trend(
    hours: int | None = Query(None, ge=1, description=_STATS_RANGE_DESC),
    start_date: str | None = Query(None, description=_START_DATE_DESC),
    end_date: str | None = Query(None, description=_END_DATE_DESC),
):
    return ApiResponse.ok(service.get_daily_trend(hours, start_date, end_date))


@router.get("/logs", response_model=ApiResponse[PageResponse[NotifyLogItem]])
def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    hours: int | None = Query(None, ge=1, description=_STATS_RANGE_DESC),
    start_date: str | None = Query(None, description=_START_DATE_DESC),
    end_date: str | None = Query(None, description=_END_DATE_DESC),
):
    items, total = service.get_logs(page, page_size, hours, start_date, end_date)
    return ApiResponse.ok(PageResponse.of(items, total, page, page_size))


@router.get("/chain/{chain_id}", response_model=ApiResponse[list[NotifyLogItem]])
def get_chain_detail(chain_id: str):
    return ApiResponse.ok(service.get_chain_detail(chain_id))
