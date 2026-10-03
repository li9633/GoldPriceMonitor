"""持仓与购买计划服务。

取数（`PortfolioMapper`）与计算（`service.position` 的纯函数）分开：
本层只负责编排放、校验与模型转换。
"""

from mapper.portfolio_mapper import PortfolioMapper
from mapper.price_mapper import PriceMapper
from models.portfolio import (
    PortfolioSummary,
    PurchaseLotCreate,
    PurchaseLotResponse,
    PurchaseLotUpdate,
    PurchasePlanCreate,
    PurchasePlanResponse,
    PurchasePlanUpdate,
)
from service.position import compute_position, summarize_plans, summarize_totals
from utils.logger import get_logger

logger = get_logger("PortfolioService")


class PortfolioService:
    """买入流水与购买计划 — 读写业务数据，不涉及行情推送"""

    def __init__(self) -> None:
        self.mapper = PortfolioMapper()
        self.price_mapper = PriceMapper()

    # ==================== 买入批次 ====================

    def list_lots(self, symbol: str | None = None) -> list[PurchaseLotResponse]:
        return [
            PurchaseLotResponse(**row) for row in self.mapper.list_lots(symbol)
        ]

    def create_lot(self, payload: PurchaseLotCreate) -> PurchaseLotResponse:
        data = payload.model_dump()
        self._ensure_plan_exists(data.get("plan_id"))
        lot_id = self.mapper.insert_lot(data)
        created = self.mapper.get_lot(lot_id)
        if created is None:  # pragma: no cover - 插入后必然可读
            raise RuntimeError("买入记录写入失败")
        return PurchaseLotResponse(**created)

    def update_lot(
        self, lot_id: int, payload: PurchaseLotUpdate
    ) -> PurchaseLotResponse | None:
        if self.mapper.get_lot(lot_id) is None:
            return None
        changes = payload.model_dump(exclude_unset=True)
        if "plan_id" in changes:
            self._ensure_plan_exists(changes["plan_id"])
        if changes:
            self.mapper.update_lot(lot_id, changes)
        updated = self.mapper.get_lot(lot_id)
        return PurchaseLotResponse(**updated) if updated else None

    def delete_lot(self, lot_id: int) -> bool:
        return self.mapper.delete_lot(lot_id)

    def _ensure_plan_exists(self, plan_id: int | None) -> None:
        if plan_id is None:
            return
        if self.mapper.get_plan(int(plan_id)) is None:
            raise ValueError(f"购买计划 {plan_id} 不存在")

    # ==================== 购买计划 ====================

    def list_plans(
        self, symbol: str | None = None, status: str | None = None
    ) -> list[PurchasePlanResponse]:
        return [
            PurchasePlanResponse(**row)
            for row in self.mapper.list_plans(symbol, status)
        ]

    def create_plan(self, payload: PurchasePlanCreate) -> PurchasePlanResponse:
        plan_id = self.mapper.insert_plan(payload.model_dump())
        created = self.mapper.get_plan(plan_id)
        if created is None:  # pragma: no cover
            raise RuntimeError("购买计划写入失败")
        return PurchasePlanResponse(**created)

    def update_plan(
        self, plan_id: int, payload: PurchasePlanUpdate
    ) -> PurchasePlanResponse | None:
        if self.mapper.get_plan(plan_id) is None:
            return None
        changes = payload.model_dump(exclude_unset=True)
        if changes:
            self.mapper.update_plan(plan_id, changes)
        updated = self.mapper.get_plan(plan_id)
        return PurchasePlanResponse(**updated) if updated else None

    def delete_plan(self, plan_id: int) -> bool:
        """删除计划但保留买入记录（关联批次的 plan_id 会被置空）"""
        return self.mapper.delete_plan(plan_id)

    # ==================== 持仓总览 ====================

    def get_summary(self, symbol: str | None = None) -> PortfolioSummary:
        """按品种汇总持仓，并给出计划进度与合计。

        拿不到最新价的品种，其市值与盈亏返回 `None`（而不是 0），
        合计也相应返回 `None`，避免把「没有行情」显示成「刚好持平」。
        """
        lots = self.mapper.list_lots(symbol)
        symbols = sorted({str(lot["symbol"]) for lot in lots})

        positions = [
            compute_position(
                sym,
                [lot for lot in lots if lot["symbol"] == sym],
                self.price_mapper.get_latest_price(sym),
            )
            for sym in symbols
        ]

        plans = self.mapper.list_plans(symbol)
        progress = summarize_plans(plans, lots)

        return PortfolioSummary(
            positions=positions,
            plans=progress,
            **summarize_totals(positions),
        )
