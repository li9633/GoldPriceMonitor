"""持仓与购买计划服务。

取数（`PortfolioMapper`）与计算（`service.position` 的纯函数）分开：
本层只负责编排、校验与模型转换。

**超卖校验**：账本出现「卖出多于持仓」会让成本价与已实现盈亏静默失真，所以每次改动
买入/卖出记录前先重走一遍账本，不通过就拒绝这次编辑。
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
    SaleRecordCreate,
    SaleRecordResponse,
    SaleRecordUpdate,
)
from service.position import (
    compute_position,
    realized_pnl_by_sale,
    summarize_plans,
    summarize_totals,
    validate_ledger,
)
from utils.logger import get_logger

logger = get_logger("PortfolioService")


class PortfolioService:
    """买入/卖出流水与购买计划 — 读写业务数据，不涉及行情推送"""

    def __init__(self) -> None:
        self.mapper = PortfolioMapper()
        self.price_mapper = PriceMapper()

    # ==================== 账本一致性 ====================

    def _ensure_ledger_ok(self, symbols: set[str]) -> None:
        """重走账本，出现超卖就抛 `ValueError`"""
        for symbol in sorted(symbols):
            if not symbol:
                continue
            problem = validate_ledger(
                self.mapper.list_lots(symbol), self.mapper.list_sales(symbol)
            )
            if problem:
                raise ValueError(f"{symbol}：{problem}")

    def _ensure_ledger_ok_with(
        self,
        symbols: set[str],
        *,
        replace_lot: dict | None = None,
        replace_sale: dict | None = None,
    ) -> None:
        """用「改动之后的样子」预演一遍账本。

        刻意**先校验再落库**，而不是写完再回滚 —— 回滚要按原 id 重新插回一行，
        稍有不慎就会把 id 弄丢（进而让 plan_id 之类的引用悬空）。
        """
        for symbol in sorted(s for s in symbols if s):
            lots = [
                row
                for row in self.mapper.list_lots(symbol)
                if replace_lot is None or row["id"] != replace_lot["id"]
            ]
            sales = [
                row
                for row in self.mapper.list_sales(symbol)
                if replace_sale is None or row["id"] != replace_sale["id"]
            ]
            if replace_lot is not None and str(replace_lot["symbol"]) == symbol:
                lots.append(replace_lot)
            if replace_sale is not None and str(replace_sale["symbol"]) == symbol:
                sales.append(replace_sale)
            problem = validate_ledger(lots, sales)
            if problem:
                raise ValueError(f"{symbol}：{problem}")

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
        before = self.mapper.get_lot(lot_id)
        if before is None:
            return None
        changes = payload.model_dump(exclude_unset=True)
        if "plan_id" in changes:
            self._ensure_plan_exists(changes["plan_id"])
        if not changes:
            return PurchaseLotResponse(**before)

        candidate = {**before, **changes}
        # 买入被改小或日期提前，都可能让已有卖出变成超卖 —— 先校验再落库
        self._ensure_ledger_ok_with(
            {str(before["symbol"]), str(candidate["symbol"])}, replace_lot=candidate
        )
        self.mapper.update_lot(lot_id, changes)
        updated = self.mapper.get_lot(lot_id) or before
        return PurchaseLotResponse(**updated)

    def delete_lot(self, lot_id: int) -> bool:
        before = self.mapper.get_lot(lot_id)
        if before is None:
            return False
        # 删掉一笔买入可能让已有卖出变成超卖
        self._ensure_ledger_ok_with(
            {str(before["symbol"])},
            replace_lot={**before, "grams": 0.0, "id": before["id"]},
        )
        return self.mapper.delete_lot(lot_id)

    def _ensure_plan_exists(self, plan_id: int | None) -> None:
        if plan_id is None:
            return
        if self.mapper.get_plan(int(plan_id)) is None:
            raise ValueError(f"购买计划 {plan_id} 不存在")

    # ==================== 卖出记录 ====================

    def list_sales(self, symbol: str | None = None) -> list[SaleRecordResponse]:
        """列出卖出记录，并回填每笔的已实现盈亏（移动平均口径）"""
        sales = self.mapper.list_sales(symbol)
        if not sales:
            return []

        pnl_map: dict[int, float] = {}
        for sym in {str(row["symbol"]) for row in sales}:
            pnl_map.update(
                realized_pnl_by_sale(
                    [row for row in sales if str(row["symbol"]) == sym],
                    self.mapper.list_lots(sym),
                )
            )
        return [
            SaleRecordResponse(
                **{**row, "realized_pnl": round(pnl_map.get(int(row["id"]), 0.0), 2)}
            )
            for row in sales
        ]

    def create_sale(self, payload: SaleRecordCreate) -> SaleRecordResponse:
        data = payload.model_dump()
        sale_id = self.mapper.insert_sale(data)
        try:
            self._ensure_ledger_ok({str(data["symbol"])})
        except ValueError:
            self.mapper.delete_sale(sale_id)
            raise
        created = self.mapper.get_sale(sale_id)
        if created is None:  # pragma: no cover
            raise RuntimeError("卖出记录写入失败")
        return self._with_pnl(created)

    def update_sale(
        self, sale_id: int, payload: SaleRecordUpdate
    ) -> SaleRecordResponse | None:
        before = self.mapper.get_sale(sale_id)
        if before is None:
            return None
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self._with_pnl(before)

        candidate = {**before, **changes}
        self._ensure_ledger_ok_with(
            {str(before["symbol"]), str(candidate["symbol"])}, replace_sale=candidate
        )
        self.mapper.update_sale(sale_id, changes)
        updated = self.mapper.get_sale(sale_id) or before
        return self._with_pnl(updated)

    def delete_sale(self, sale_id: int) -> bool:
        """删除卖出记录 —— 只会让持仓变多，不会造成超卖，无需校验"""
        return self.mapper.delete_sale(sale_id)

    def _with_pnl(self, sale: dict) -> SaleRecordResponse:
        lots = self.mapper.list_lots(str(sale["symbol"]))
        pnl = realized_pnl_by_sale([sale], lots).get(int(sale["id"]), 0.0)
        return SaleRecordResponse(**{**sale, "realized_pnl": round(pnl, 2)})

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

        品种集合取**买入与卖出的并集** —— 全部卖光的品种仍然要出现在列表里，
        否则用户看不到它的已实现盈亏。
        """
        lots = self.mapper.list_lots(symbol)
        sales = self.mapper.list_sales(symbol)
        symbols = sorted(
            {str(row["symbol"]) for row in lots}
            | {str(row["symbol"]) for row in sales}
        )

        positions = [
            compute_position(
                sym,
                [row for row in lots if str(row["symbol"]) == sym],
                self.price_mapper.get_latest_price(sym),
                sales=[row for row in sales if str(row["symbol"]) == sym],
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
