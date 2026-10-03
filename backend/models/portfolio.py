"""持仓与购买计划的数据模型。

分三层：
- `PurchaseLot*`：买入批次（追加式流水），回答「买了多少、什么价、什么渠道」
- `PurchasePlan*`：购买计划，回答「分批还是一次性」
- `PositionSummary` / `PlanProgress` / `PortfolioSummary`：由流水推导出的视图，**不落库**

成本口径（阶段 1 已确认）：统一按「克」计算，**手续费只记录、不摊入成本**，
即 `总成本 = Σ(克数 × 单价)`。手续费单独用 `total_fee` 展示，以后若要按渠道精算
无需改表。
"""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field, field_validator


def _validate_trade_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
    return value


# ==================== 买入批次 ====================


class PurchaseLotBase(BaseModel):
    """买入批次基础字段"""

    symbol: str = Field(..., min_length=1, description="品种代码", examples=["gds_AUTD"])
    trade_date: str = Field(..., description="买入日期（YYYY-MM-DD）")
    grams: float = Field(..., gt=0, description="买入克数")
    price_per_gram: float = Field(..., gt=0, description="买入单价（元/克）")
    fee: float = Field(default=0.0, ge=0, description="手续费（只记录，不摊入成本）")
    channel: str = Field(default="", description="渠道，如 金店 / 银行积存金 / ETF")
    note: str = Field(default="", description="备注")

    @field_validator("trade_date")
    @classmethod
    def check_trade_date(cls, value: str) -> str:
        return _validate_trade_date(value)


class PurchaseLotCreate(PurchaseLotBase):
    """创建买入批次 — POST 请求体"""

    plan_id: int | None = Field(default=None, description="归属的购买计划 ID")


class PurchaseLotUpdate(BaseModel):
    """更新买入批次 — PUT 请求体，全部字段可选"""

    symbol: str | None = Field(default=None, min_length=1)
    trade_date: str | None = None
    grams: float | None = Field(default=None, gt=0)
    price_per_gram: float | None = Field(default=None, gt=0)
    fee: float | None = Field(default=None, ge=0)
    channel: str | None = None
    note: str | None = None
    plan_id: int | None = None

    @field_validator("trade_date")
    @classmethod
    def check_trade_date(cls, value: str | None) -> str | None:
        return None if value is None else _validate_trade_date(value)


class PurchaseLotResponse(PurchaseLotBase):
    """买入批次 — GET 返回体"""

    id: int
    plan_id: int | None = None
    created_at: str = ""

    @computed_field(description="买入金额（不含手续费）")
    @property
    def amount(self) -> float:
        return round(self.grams * self.price_per_gram, 2)


# ==================== 购买计划 ====================


class PurchasePlanBase(BaseModel):
    """购买计划基础字段"""

    symbol: str = Field(..., min_length=1, description="品种代码")
    target_grams: float = Field(..., gt=0, description="计划买入总克数")
    budget: float | None = Field(default=None, ge=0, description="计划预算（可选）")
    tranches: int = Field(default=1, ge=1, description="计划分几批，1 表示一次性")
    tranche_grams: float | None = Field(
        default=None, gt=0, description="每批克数（可选，默认由总克数均分）"
    )
    trigger_policy: dict = Field(
        default_factory=dict,
        description="触发策略，如 {'type': 'interval', 'days': 7} 或 "
        "{'type': 'drop_pct', 'pct': 1.0}",
    )
    start_date: str | None = Field(default=None, description="计划开始日期")
    end_date: str | None = Field(default=None, description="计划结束日期")
    status: str = Field(
        default="active", description="状态：active / paused / done / cancelled"
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def check_optional_date(cls, value: str | None) -> str | None:
        return None if value is None else _validate_trade_date(value)

    @field_validator("status")
    @classmethod
    def check_status(cls, value: str) -> str:
        allowed = {"active", "paused", "done", "cancelled"}
        if value not in allowed:
            raise ValueError(f"状态必须是 {sorted(allowed)} 之一")
        return value


class PurchasePlanCreate(PurchasePlanBase):
    """创建购买计划 — POST 请求体"""


class PurchasePlanUpdate(BaseModel):
    """更新购买计划 — PUT 请求体，全部字段可选"""

    symbol: str | None = Field(default=None, min_length=1)
    target_grams: float | None = Field(default=None, gt=0)
    budget: float | None = Field(default=None, ge=0)
    tranches: int | None = Field(default=None, ge=1)
    tranche_grams: float | None = Field(default=None, gt=0)
    trigger_policy: dict | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def check_optional_date(cls, value: str | None) -> str | None:
        return None if value is None else _validate_trade_date(value)

    @field_validator("status")
    @classmethod
    def check_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"active", "paused", "done", "cancelled"}
        if value not in allowed:
            raise ValueError(f"状态必须是 {sorted(allowed)} 之一")
        return value


class PurchasePlanResponse(PurchasePlanBase):
    """购买计划 — GET 返回体"""

    id: int
    created_at: str = ""
    updated_at: str = ""


# ==================== 推导视图（不落库） ====================


class PositionSummary(BaseModel):
    """单个品种的持仓汇总 — 由买入批次实时推导"""

    symbol: str = Field(..., description="品种代码")
    lot_count: int = Field(default=0, description="批次数量")
    total_grams: float = Field(default=0.0, description="持仓总克数")
    total_cost: float = Field(default=0.0, description="总成本（不含手续费）")
    total_fee: float = Field(default=0.0, description="累计手续费")
    avg_cost: float = Field(default=0.0, description="持仓成本价（元/克）")
    latest_price: float | None = Field(default=None, description="最新价（元/克）")
    market_value: float | None = Field(default=None, description="当前市值")
    unrealized_pnl: float | None = Field(default=None, description="浮动盈亏")
    unrealized_pnl_pct: float | None = Field(default=None, description="浮动盈亏比例(%)")
    first_trade_date: str | None = Field(default=None, description="首笔买入日期")
    last_trade_date: str | None = Field(default=None, description="最近一笔买入日期")


class PlanProgress(BaseModel):
    """购买计划的执行进度 — 由买入批次实时推导"""

    plan_id: int
    symbol: str
    target_grams: float
    filled_grams: float = Field(default=0.0, description="已买入克数")
    remaining_grams: float = Field(default=0.0, description="剩余待买克数")
    progress_pct: float = Field(default=0.0, description="完成比例(%)")
    tranches: int = Field(default=1, description="计划批次数")
    filled_tranches: int = Field(default=0, description="已买入批次数")
    invested_amount: float = Field(default=0.0, description="已投入金额")
    avg_cost: float = Field(default=0.0, description="该计划下的成本价")
    status: str
    start_date: str | None = None
    end_date: str | None = None


class PortfolioSummary(BaseModel):
    """持仓总览 — 按品种分组，并给出合计"""

    positions: list[PositionSummary] = Field(default_factory=list)
    plans: list[PlanProgress] = Field(default_factory=list)
    total_grams: float = Field(default=0.0)
    total_cost: float = Field(default=0.0)
    total_fee: float = Field(default=0.0)
    total_market_value: float | None = Field(default=None)
    total_unrealized_pnl: float | None = Field(default=None)
    total_unrealized_pnl_pct: float | None = Field(default=None)
    priced_symbols: list[str] = Field(
        default_factory=list, description="拿到了最新价的品种"
    )
