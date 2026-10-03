"""持仓计算 —— 纯函数，不碰数据库，便于单测。

输入是 `PortfolioMapper` 返回的普通 dict 行，输出是 `models.portfolio` 里的视图模型。
把计算和取数分开，是为了让「成本价 / 浮盈亏 / 计划进度」这些真正决定建议对不对的
算术可以被独立测试，而不是埋在 SQL 或接口层里。

**成本口径（阶段 1 已确认）**：统一按「克」，手续费只记录、不摊入成本，
即 `总成本 = Σ(克数 × 单价)`。`total_fee` 单独返回以便展示。
"""

from models.portfolio import PlanProgress, PositionSummary


def _grams(lot: dict) -> float:
    return float(lot.get("grams") or 0)


def _price(lot: dict) -> float:
    return float(lot.get("price_per_gram") or 0)


def _fee(lot: dict) -> float:
    return float(lot.get("fee") or 0)


def compute_position(
    symbol: str,
    lots: list[dict],
    latest_price: float | None = None,
) -> PositionSummary:
    """由买入批次推导单个品种的持仓汇总。

    `latest_price` 为 `None` 时（拿不到行情）市值与盈亏返回 `None`，
    而不是 0 —— 0 会被误读成「持平」。
    """
    if not lots:
        return PositionSummary(symbol=symbol, latest_price=latest_price)

    total_grams = sum(_grams(lot) for lot in lots)
    total_cost = sum(_grams(lot) * _price(lot) for lot in lots)
    total_fee = sum(_fee(lot) for lot in lots)
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
        total_fee=round(total_fee, 2),
        avg_cost=round(avg_cost, 4),
        latest_price=latest_price,
        market_value=None if market_value is None else round(market_value, 2),
        unrealized_pnl=None if unrealized_pnl is None else round(unrealized_pnl, 2),
        unrealized_pnl_pct=(
            None if unrealized_pnl_pct is None else round(unrealized_pnl_pct, 2)
        ),
        first_trade_date=dates[0],
        last_trade_date=dates[-1],
    )


def compute_plan_progress(plan: dict, lots: list[dict]) -> PlanProgress:
    """由买入批次推导购买计划的执行进度。

    `filled_tranches` 用「关联到该计划的批次数」定义 —— 每笔买入算一批。
    `progress_pct` 不做上限截断，超买时会大于 100，由展示层决定怎么呈现。
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

    total_market_value = sum(p.market_value for p in priced) if all_priced else None
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
        "priced_symbols": [p.symbol for p in priced],
    }
