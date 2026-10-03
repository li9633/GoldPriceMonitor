"""持仓与购买计划接口。

约定与其它 controller 一致：service 抛 `ValueError` 表示入参不合法（→400），
返回 `None` 表示目标不存在（→404）。
"""

from fastapi import APIRouter, Query

from models.portfolio import (
    PortfolioSummary,
    PurchaseLotCreate,
    PurchaseLotResponse,
    PurchaseLotUpdate,
    PurchasePlanCreate,
    PurchasePlanResponse,
    PurchasePlanUpdate,
)
from models.response import ApiResponse
from service.portfolio_service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["持仓与购买计划"])

service = PortfolioService()

_SYMBOL_DESC = "品种代码，不传表示全部品种"


# ==================== 买入批次 ====================


@router.get("/lots", response_model=ApiResponse[list[PurchaseLotResponse]])
def list_lots(symbol: str | None = Query(None, description=_SYMBOL_DESC)):
    return ApiResponse.ok(service.list_lots(symbol))


@router.post("/lots", response_model=ApiResponse[PurchaseLotResponse])
def create_lot(payload: PurchaseLotCreate):
    try:
        return ApiResponse.ok(service.create_lot(payload))
    except ValueError as exc:
        return ApiResponse.fail(str(exc), code=400)


@router.put("/lots/{lot_id}", response_model=ApiResponse[PurchaseLotResponse])
def update_lot(lot_id: int, payload: PurchaseLotUpdate):
    try:
        updated = service.update_lot(lot_id, payload)
    except ValueError as exc:
        return ApiResponse.fail(str(exc), code=400)
    if updated is None:
        return ApiResponse.fail(f"买入记录 {lot_id} 不存在", code=404)
    return ApiResponse.ok(updated)


@router.delete("/lots/{lot_id}", response_model=ApiResponse[None])
def delete_lot(lot_id: int):
    if not service.delete_lot(lot_id):
        return ApiResponse.fail(f"买入记录 {lot_id} 不存在", code=404)
    return ApiResponse.success("已删除")


# ==================== 购买计划 ====================


@router.get("/plans", response_model=ApiResponse[list[PurchasePlanResponse]])
def list_plans(
    symbol: str | None = Query(None, description=_SYMBOL_DESC),
    status: str | None = Query(
        None, description="状态筛选：active / paused / done / cancelled"
    ),
):
    return ApiResponse.ok(service.list_plans(symbol, status))


@router.post("/plans", response_model=ApiResponse[PurchasePlanResponse])
def create_plan(payload: PurchasePlanCreate):
    try:
        return ApiResponse.ok(service.create_plan(payload))
    except ValueError as exc:
        return ApiResponse.fail(str(exc), code=400)


@router.put("/plans/{plan_id}", response_model=ApiResponse[PurchasePlanResponse])
def update_plan(plan_id: int, payload: PurchasePlanUpdate):
    try:
        updated = service.update_plan(plan_id, payload)
    except ValueError as exc:
        return ApiResponse.fail(str(exc), code=400)
    if updated is None:
        return ApiResponse.fail(f"购买计划 {plan_id} 不存在", code=404)
    return ApiResponse.ok(updated)


@router.delete("/plans/{plan_id}", response_model=ApiResponse[None])
def delete_plan(plan_id: int):
    if not service.delete_plan(plan_id):
        return ApiResponse.fail(f"购买计划 {plan_id} 不存在", code=404)
    return ApiResponse.success("已删除，关联的买入记录已保留")


# ==================== 持仓总览 ====================


@router.get("/summary", response_model=ApiResponse[PortfolioSummary])
def get_summary(symbol: str | None = Query(None, description=_SYMBOL_DESC)):
    return ApiResponse.ok(service.get_summary(symbol))
