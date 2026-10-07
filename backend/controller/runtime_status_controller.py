"""运行状态查询接口 —— 程序自身运行指标的只读暴露。"""

from fastapi import APIRouter

from models.response import ApiResponse
from service.runtime_status_service import get_runtime_status

router = APIRouter(prefix="/runtime-status", tags=["运行状态"])


@router.get("")
def read_runtime_status():
    """当前运行状态：启停、运行时长、巡检/投递计数、最近巡检记录与最近错误"""
    return ApiResponse.ok(get_runtime_status().snapshot())
