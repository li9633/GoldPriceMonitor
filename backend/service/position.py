"""持仓计算 —— 纯函数，不碰数据库，便于单测。

输入是 `PortfolioMapper` 返回的普通 dict 行，输出是 `models.portfolio` 里的视图模型。

**成本口径**：统一按「克」，手续费只记录、不摊入成本，即 `总成本 = Σ(克数 × 单价)`。

**卖出按移动平均结转**：按卖出当时的持仓均价计算，剩余持仓的成本价不变
（`(cost − avg×s) / (grams − s) = avg`）。均价随买入变化，所以已实现盈亏必须按
买入与卖出合并后的账本顺序推导，不能用最终均价乘总卖出量。
"""

from dataclasses import dataclass

from models.portfolio import PlanProgress, PositionSummary

#: 账本事件类型
BUY = "buy"
SELL = "sell"


def _grams(row: dict) -> float:
    return float(row.get("grams") or 0)


def _price(row: dict) -> float:
    return float(row.get("price_per_gram") or 0)


def _fee(row: dict) -> float:
    return float(row.get("fee") or 0)


@dataclass(frozen=True)
class LedgerEvent:
    """账本上的一件事（买入或卖出）"""

    date: str
    kind: str
    grams: float
    price: float
    fee: float
    row_id: int


def build_ledger(lots: list[dict], sales: list[dict]) -> list[LedgerEvent]:
    """把买入与卖出合并成一条按时间排序的账本。

    同一天内买入排在卖出之前，避免「今天买入、今天卖出」被误判成超卖。
    """
    events = [
        LedgerEvent(
            date=str(lot.get("trade_date") or ""),
            kind=BUY,
            grams=_grams(lot),
            price=_price(lot),
            fee=_fee(lot),
            row_id=int(lot.get("id") or 0),
        )
        for lot in lots
    ]
    events += [
        LedgerEvent(
            date=str(sale.get("sale_date") or ""),
            kind=SELL,
            grams=_grams(sale),
            price=_price(sale),
            fee=_fee(sale),
            row_id=int(sale.get("id") or 0),
        )
        for sale in sales
    ]
    events.sort(key=lambda e: (e.date, 0 if e.kind == BUY else 1, e.row_id))
    return events


@dataclass
class LedgerResult:
    """账本走一遍的结果"""

    grams: float = 0.0
    cost: float = 0.0
    sold_grams: float = 0.0
    realized_pnl: float = 0.0
    #: 每笔卖出（按 `row_id`）的已实现盈亏
    realized_by_sale: dict[int, float] = None  # type: ignore[assignment]
    #: 超卖克数；正常为 0，非 0 说明数据不一致（写入时应被拦住）
    oversold_grams: float = 0.0

    def __post_init__(self) -> None:
        if self.realized_by_sale is None:
            self.realized_by_sale = {}


def walk_ledger(events: list[LedgerEvent]) -> LedgerResult:
    """按时间顺序走账本，得出剩余持仓、成本与逐笔已实现盈亏。

    超卖时不把克数扣成负数：扣到 0 为止，超出部分记在 `oversold_grams`，
    由调用方决定报错还是提示。
    """
    result = LedgerResult()
    for event in events:
        if event.kind == BUY:
            result.grams += event.grams
            result.cost += event.grams * event.price
            continue

        avg = result.cost / result.grams if result.grams > 0 else 0.0
        sold = min(event.grams, result.grams)
        pnl = (event.price - avg) * sold
        result.realized_pnl += pnl
        result.realized_by_sale[event.row_id] = pnl
        result.cost -= avg * sold
        result.grams -= sold
        result.sold_grams += sold
        if event.grams > sold:
            result.oversold_grams += event.grams - sold

        # 浮点误差可能留下 1e-12 级别的残留，清掉避免 avg_cost 出现噪声
        if abs(result.grams) < 1e-9:
            result.grams = 0.0
            result.cost = 0.0
    return result


def validate_ledger(lots: list[dict], sales: list[dict]) -> str | None:
    """账本是否自洽（有没有超卖）。

    返回 `None` 表示没问题，否则返回给用户看的中文说明。
    """
    result = walk_ledger(build_ledger(lots, sales))
    if result.oversold_grams <= 0:
        return None
    return (
        f"卖出总量超出持仓 {round(result.oversold_grams, 4)}g，"
        "请检查卖出记录，或对应的买入记录是否被改小/删除"
    )


def compute_position(
    symbol: str,
    lots: list[dict],
    latest_price: float | None = None,
    *,
    sales: list[dict] | None = None,
) -> PositionSummary:
    """由买入批次与卖出记录推导单个品种的持仓汇总。

    `latest_price` 为 `None` 时（拿不到行情）市值与盈亏返回 `None`，
    而不是 0 —— 0 会被误读成「持平」。

    `sales` 刻意做成**仅关键字参数**：它是在 `latest_price` 之后才加的，
    做成位置参数会把老调用里第三个位置上的价格当成卖出记录，静默算错。
    """
    sales = sales or []
    if not lots and not sales:
        return PositionSummary(symbol=symbol, latest_price=latest_price)

    ledger = walk_ledger(build_ledger(lots, sales))
    total_grams = ledger.grams
    total_cost = ledger.cost
    avg_cost = total_cost / total_grams if total_grams > 0 else 0.0

    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    if latest_price is not None:
        market_value = total_grams * latest_price
        unrealized_pnl = market_value - total_cost
        if total_cost > 0:
            unrealized_pnl_pct = unrealized_pnl / total_cost * 100

    dates = sorted(str(lot.get("trade_date") or "") for lot in lots)

    return PositionSummary(
        symbol=symbol,
        lot_count=len(lots),
        total_grams=round(total_grams, 4),
        total_cost=round(total_cost, 2),
        total_fee=round(sum(_fee(lot) for lot in lots), 2),
        avg_cost=round(avg_cost, 4),
        latest_price=latest_price,
        market_value=None if market_value is None else round(market_value, 2),
        unrealized_pnl=None if unrealized_pnl is None else round(unrealized_pnl, 2),
        unrealized_pnl_pct=(
            None if unrealized_pnl_pct is None else round(unrealized_pnl_pct, 2)
        ),
        first_trade_date=dates[0] if dates else None,
        last_trade_date=dates[-1] if dates else None,
        sale_count=len(sales),
        total_sold_grams=round(ledger.sold_grams, 4),
        realized_pnl=round(ledger.realized_pnl, 2),
        sale_fee=round(sum(_fee(sale) for sale in sales), 2),
    )


def realized_pnl_by_sale(sales: list[dict], lots: list[dict]) -> dict[int, float]:
    """每笔卖出的已实现盈亏（按卖出记录 id 索引），用于列表展示"""
    return walk_ledger(build_ledger(lots, sales)).realized_by_sale


def compute_plan_progress(plan: dict, lots: list[dict]) -> PlanProgress:
    """由买入批次推导购买计划的执行进度。

    `filled_tranches` 用「关联到该计划的批次数」定义 —— 每笔买入算一批。
    `progress_pct` 不做上限截断，超买时会大于 100，由展示层决定怎么呈现。

    卖出**不计入**计划进度：计划回答的是「买够了没有」，卖出不改变这个回答。
    """
    plan_id = int(plan["id"])
    filled = [lot for lot in lots if lot.get("plan_id") == plan_id]

    target_grams = float(plan.get("target_grams") or 0)
    filled_grams = sum(_grams(lot) for lot in filled)
    invested = sum(_grams(lot) * _price(lot) for lot in filled)
    avg_cost = invested / filled_grams if filled_grams > 0 else 0.0
    progress_pct = filled_grams / target_grams * 100 if target_grams > 0 else 0.0

    return PlanProgress(
        plan_id=plan_id,
        symbol=str(plan.get("symbol") or ""),
        target_grams=round(target_grams, 4),
        filled_grams=round(filled_grams, 4),
        remaining_grams=round(max(target_grams - filled_grams, 0.0), 4),
        progress_pct=round(progress_pct, 2),
        tranches=int(plan.get("tranches") or 1),
        filled_tranches=len(filled),
        invested_amount=round(invested, 2),
        avg_cost=round(avg_cost, 4),
        status=str(plan.get("status") or "active"),
        start_date=plan.get("start_date"),
        end_date=plan.get("end_date"),
    )


def summarize_plans(plans: list[dict], lots: list[dict]) -> list[PlanProgress]:
    return [compute_plan_progress(plan, lots) for plan in plans]


def summarize_totals(positions: list[PositionSummary]) -> dict:
    """跨品种合计。任一品种拿不到价格时，合计市值/盈亏返回 `None`（不静默少算）。"""
    total_grams = sum(p.total_grams for p in positions)
    total_cost = sum(p.total_cost for p in positions)
    total_fee = sum(p.total_fee for p in positions)

    priced = [p for p in positions if p.market_value is not None]
    all_priced = len(priced) == len(positions) and bool(positions)

    # 写成循环而非生成器：列表推导里的 `is not None` 过滤不会让 mypy 收窄元素类型
    market_values: list[float] = []
    for item in positions:
        if item.market_value is not None:
            market_values.append(item.market_value)

    total_market_value = sum(market_values) if all_priced else None
    total_pnl = total_market_value - total_cost if total_market_value is not None else None
    total_pnl_pct = (
        total_pnl / total_cost * 100
        if total_pnl is not None and total_cost > 0
        else None
    )

    return {
        "total_grams": round(total_grams, 4),
        "total_cost": round(total_cost, 2),
        "total_fee": round(total_fee, 2),
        "total_market_value": (
            None if total_market_value is None else round(total_market_value, 2)
        ),
        "total_unrealized_pnl": None if total_pnl is None else round(total_pnl, 2),
        "total_unrealized_pnl_pct": (
            None if total_pnl_pct is None else round(total_pnl_pct, 2)
        ),
        "total_realized_pnl": round(sum(p.realized_pnl for p in positions), 2),
        "total_sale_fee": round(sum(p.sale_fee for p in positions), 2),
        "total_sold_grams": round(sum(p.total_sold_grams for p in positions), 4),
        "priced_symbols": [p.symbol for p in priced],
    }
