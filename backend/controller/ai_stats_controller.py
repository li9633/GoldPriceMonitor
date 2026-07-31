from fastapi import APIRouter, Query

from models.ai_stats import (
    AiStatsOverview,
    TokenByModel,
    TokenDailyTrend,
    TokenOverview,
)
from models.response import ApiResponse
from service.ai_stats_service import AiStatsService

router = APIRouter(prefix="/ai-stats", tags=["AI调用统计"])
service = AiStatsService()


@router.get("/overview", response_model=ApiResponse[AiStatsOverview])
def get_overview():
    return ApiResponse.ok(service.get_overview())


@router.get("/trend")
def get_trend(
    days: int = Query(default=7, ge=1, le=90, description="统计天数"),
):
    return ApiResponse.ok(service.get_daily_trend(days))


@router.get("/logs")
def get_logs(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
):
    items, total = service.get_recent_logs(page, page_size)
    return ApiResponse.ok(
        {"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.get("/tokens/overview", response_model=ApiResponse[TokenOverview])
def get_token_overview(
    days: int = Query(default=1, ge=1, le=90, description="统计天数"),
):
    return ApiResponse.ok(service.get_token_overview(days))


@router.get("/tokens/by-model", response_model=ApiResponse[list[TokenByModel]])
def get_token_by_model(
    days: int = Query(default=1, ge=1, le=90, description="统计天数"),
):
    return ApiResponse.ok(service.get_token_by_model(days))


@router.get("/tokens/trend", response_model=ApiResponse[list[TokenDailyTrend]])
def get_token_trend(
    days: int = Query(default=7, ge=1, le=90, description="统计天数"),
):
    return ApiResponse.ok(service.get_token_daily_trend(days))
