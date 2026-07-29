from fastapi import APIRouter, Query
from pydantic import BaseModel

from models.response import ApiResponse
from service.log_service import LogService

router = APIRouter(prefix="/logs", tags=["系统日志"])
service = LogService()


class LogContentResponse(BaseModel):
    lines: list[str]
    total_lines: int
    file_size: int
    file_name: str


@router.get("/content", response_model=ApiResponse[LogContentResponse])
def get_log_content(
    lines: int = Query(default=200, ge=1, le=1000, description="返回行数"),
    offset: int = Query(default=0, ge=0, description="偏移量（跳过最新 N 行）"),
    level: str | None = Query(
        default=None, description="按级别过滤：DEBUG/INFO/WARNING/ERROR"
    ),
    search: str | None = Query(default=None, description="关键词搜索"),
):
    return ApiResponse.ok(
        LogContentResponse(
            **service.get_content(
                lines=lines, offset=offset, level=level, search=search
            )
        )
    )
