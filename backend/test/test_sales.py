"""卖出记账与移动平均成本结转测试。

这一层的正确性全靠**账本顺序**：均价会随买入变化，所以已实现盈亏必须按
「买入与卖出按时间合并后」逐笔推导。拿最终均价乘总卖出量是错的，
而且不会报错 —— 只会安静地给出一个错数字。

运行
----
    cd backend
    python -m test.test_sales
"""

import contextlib
import os
import tempfile

from mapper.portfolio_mapper import PortfolioMapper
from models.portfolio import (
    PurchaseLotCreate,
    SaleRecordCreate,
    SaleRecordUpdate,
)
from service.portfolio_service import PortfolioService
from service.position import (
    build_ledger,
    compute_position,
    realized_pnl_by_sale,
    validate_ledger,
    walk_ledger,
)


@contextlib.contextmanager
def assert_raises(exc_type: type[BaseException], match: str | None = None):
    try:
        yield
    except exc_type as exc:
        if match is not None and str(match) not in str(exc):
            raise AssertionError(f"异常信息中不含 {match!r}：{exc}") from exc
    else:
        raise AssertionError(f"未按预期抛出 {exc_type.__name__}")


@contextlib.contextmanager
def temp_db(name: str):
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, name)
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(base + suffix):
                os.remove(base + suffix)
        yield base


def lot(date: str, grams: float, price: float, lot_id: int = 0, symbol="gds_AUTD") -> dict:
    return {
        "id": lot_id,
        "symbol": symbol,
        "trade_date": date,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
    }


def sale(date: str, grams: float, price: float, sale_id: int = 0, symbol="gds_AUTD") -> dict:
    return {
        "id": sale_id,
        "symbol": symbol,
        "sale_date": date,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
    }


def make_service(db: str) -> PortfolioService:
    service = object.__new__(PortfolioService)
    service.mapper = PortfolioMapper(db_file=db)

    class NoPrice:
        def get_latest_price(self, symbol):
            return None

    service.price_mapper = NoPrice()
    return service


# ==================== 1. 账本顺序 ====================


def test_ledger_puts_buys_before_sells_on_same_day() -> None:
    """同一天先买后卖是自然读法，也避免「今天买、今天卖」被判成超卖"""
    events = build_ledger(
        [lot("2026-01-01", 10, 900)], [sale("2026-01-01", 10, 950)]
    )
    assert [e.kind for e in events] == ["buy", "sell"]


def test_ledger_sorts_by_date_then_kind() -> None:
    events = build_ledger(
        [
            lot("2026-03-01", 1, 900, lot_id=3),
            lot("2026-01-01", 1, 900, lot_id=1),
        ],
        [sale("2026-02-01", 1, 950, sale_id=9)],
    )
    assert [e.date for e in events] == ["2026-01-01", "2026-02-01", "2026-03-01"]


# ==================== 2. 移动平均算术 ====================


def test_realized_pnl_simple_profit() -> None:
    """10g @900 全卖 @950 → 已实现 +500，持仓归零"""
    position = compute_position(
        "gds_AUTD", [lot("2026-01-01", 10, 900)], 950.0,
        sales=[sale("2026-02-01", 10, 950, sale_id=1)],
    )
    assert position.realized_pnl == 500.0
    assert position.total_grams == 0.0
    assert position.total_cost == 0.0
    assert position.total_sold_grams == 10.0
    assert position.sale_count == 1


def test_partial_sale_keeps_avg_cost_unchanged() -> None:
    """移动平均的关键性质：卖出一部分后，剩余持仓的成本价不变"""
    position = compute_position(
        "gds_AUTD", [lot("2026-01-01", 10, 900)], 950.0,
        sales=[sale("2026-02-01", 4, 950, sale_id=1)],
    )
    assert position.avg_cost == 900.0, "移动平均下卖出不改变成本价"
    assert position.total_grams == 6.0
    assert position.total_cost == 5400.0
    assert position.realized_pnl == 200.0  # (950 - 900) * 4


def test_avg_cost_uses_chronological_buys_not_final_average() -> None:
    """核心算例：均价在两次买入之间是 900，卖出必须按 900 结转，而不是按最终 950

    买 10g @900 → 卖 10g @1000（此时均价 900，已实现 +1000）
    → 再买 10g @1000。若错用最终均价 950，会算成 +500。
    """
    lots = [lot("2026-01-01", 10, 900, lot_id=1), lot("2026-03-01", 10, 1000, lot_id=2)]
    sales = [sale("2026-02-01", 10, 1000, sale_id=1)]

    position = compute_position("gds_AUTD", lots, 1000.0, sales=sales)
    assert position.realized_pnl == 1000.0, "应按卖出当时的均价 900 结转"
    assert position.total_grams == 10.0
    assert position.avg_cost == 1000.0, "剩余那批的成本就是 1000"

    by_sale = realized_pnl_by_sale(sales, lots)
    assert by_sale == {1: 1000.0}


def test_multiple_sales_each_use_their_own_average() -> None:
    lots = [lot("2026-01-01", 10, 900, lot_id=1), lot("2026-04-01", 10, 1100, lot_id=2)]
    sales = [
        sale("2026-02-01", 5, 1000, sale_id=1),  # 均价 900 → +500
        sale("2026-05-01", 5, 1100, sale_id=2),  # 均价 (4500+11000)/15=1033.33 → +333.33
    ]
    position = compute_position("gds_AUTD", lots, 1100.0, sales=sales)
    assert position.realized_pnl == round(500 + (1100 - 1033.333333) * 5, 2)
    by_sale = realized_pnl_by_sale(sales, lots)
    assert by_sale[1] == 500.0
    assert by_sale[2] > 0


def test_loss_is_negative() -> None:
    position = compute_position(
        "gds_AUTD", [lot("2026-01-01", 10, 900)], 800.0,
        sales=[sale("2026-02-01", 10, 800, sale_id=1)],
    )
    assert position.realized_pnl == -1000.0


def test_buy_after_full_sale_restarts_cost() -> None:
    lots = [lot("2026-01-01", 10, 900, lot_id=1), lot("2026-03-01", 5, 1200, lot_id=2)]
    sales = [sale("2026-02-01", 10, 1000, sale_id=1)]
    position = compute_position("gds_AUTD", lots, 1200.0, sales=sales)
    assert position.total_grams == 5.0
    assert position.avg_cost == 1200.0, "清仓后重新买入，成本从头算"
    assert position.realized_pnl == 1000.0


def test_fees_are_recorded_but_not_netted() -> None:
    """沿用「手续费只记录不摊入成本」的口径，已实现盈亏为税前"""
    lots = [dict(lot("2026-01-01", 10, 900), fee=30.0)]
    sales = [dict(sale("2026-02-01", 10, 950, sale_id=1), fee=20.0)]
    position = compute_position("gds_AUTD", lots, 950.0, sales=sales)
    assert position.realized_pnl == 500.0, "不扣手续费"
    assert position.total_fee == 30.0
    assert position.sale_fee == 20.0


def test_unrealized_pnl_reflects_remaining_only() -> None:
    position = compute_position(
        "gds_AUTD", [lot("2026-01-01", 10, 900)], 1000.0,
        sales=[sale("2026-02-01", 6, 950, sale_id=1)],
    )
    assert position.total_grams == 4.0
    assert position.market_value == 4000.0
    assert position.unrealized_pnl == 4000.0 - 3600.0
    assert position.unrealized_pnl_pct == round(400 / 3600 * 100, 2)


def test_no_price_still_reports_realized_pnl() -> None:
    """拿不到行情时浮动盈亏是 None，但已实现盈亏照样有值"""
    position = compute_position(
        "gds_AUTD", [lot("2026-01-01", 10, 900)], None,
        sales=[sale("2026-02-01", 10, 950, sale_id=1)],
    )
    assert position.unrealized_pnl is None
    assert position.realized_pnl == 500.0


# ==================== 3. 超卖 ====================


def test_walk_ledger_clamps_oversell() -> None:
    """超卖时不把克数扣成负数，而是记在 oversold_grams"""
    result = walk_ledger(build_ledger([lot("2026-01-01", 5, 900)], [sale("2026-02-01", 8, 950)]))
    assert result.grams == 0.0
    assert result.oversold_grams == 3.0
    assert result.sold_grams == 5.0, "只结转真正持有的部分"


def test_validate_ledger_reports_oversell() -> None:
    ok = validate_ledger([lot("2026-01-01", 10, 900)], [sale("2026-02-01", 10, 950)])
    assert ok is None

    bad = validate_ledger([lot("2026-01-01", 10, 900)], [sale("2026-02-01", 12, 950)])
    assert bad is not None and "超出持仓" in bad


def test_sale_before_the_buy_is_oversell() -> None:
    """按日期排：卖出在买入之前 → 当时无持仓可卖"""
    problem = validate_ledger(
        [lot("2026-03-01", 10, 900)], [sale("2026-02-01", 1, 950)]
    )
    assert problem is not None


# ==================== 4. 服务层校验与回滚 ====================


def test_create_sale_rejects_oversell_and_rolls_back() -> None:
    with temp_db("sale_guard.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))

        with assert_raises(ValueError, "超出持仓"):
            service.create_sale(
                SaleRecordCreate(
                    symbol="gds_AUTD", sale_date="2026-02-01", grams=12.0,
                    price_per_gram=950.0,
                )
            )
        assert service.mapper.list_sales() == [], "被拒绝的卖出不该留在库里"


def test_create_sale_accepts_exact_holding() -> None:
    with temp_db("sale_ok.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        created = service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=950.0,
            )
        )
        assert created.grams == 10.0
        assert created.amount == 9500.0
        assert created.realized_pnl == 500.0
        assert service.mapper.list_sales()[0]["grams"] == 10.0


def test_shrinking_a_lot_below_sold_amount_is_rejected() -> None:
    with temp_db("shrink.db") as db:
        service = make_service(db)
        lot_id = service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=950.0,
            )
        )

        from models.portfolio import PurchaseLotUpdate

        with assert_raises(ValueError, "超出持仓"):
            service.update_lot(lot_id, PurchaseLotUpdate(grams=5.0))
        assert service.mapper.get_lot(lot_id)["grams"] == 10.0, "失败的编辑应被回滚"


def test_deleting_a_lot_that_covers_a_sale_is_rejected() -> None:
    with temp_db("dellot.db") as db:
        service = make_service(db)
        lot_id = service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=950.0,
            )
        )
        with assert_raises(ValueError, "超出持仓"):
            service.delete_lot(lot_id)
        assert service.mapper.get_lot(lot_id) is not None, "失败的删除应被回滚"


def test_update_sale_rejects_oversell() -> None:
    with temp_db("upsale.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        created = service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=5.0,
                price_per_gram=950.0,
            )
        )
        with assert_raises(ValueError, "超出持仓"):
            service.update_sale(created.id, SaleRecordUpdate(grams=20.0))
        assert service.mapper.get_sale(created.id)["grams"] == 5.0, "失败的编辑应被回滚"


def test_delete_sale_always_allowed() -> None:
    """删除卖出只会让持仓变多，不需要校验"""
    with temp_db("delsale.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        created = service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=950.0,
            )
        )
        assert service.delete_sale(created.id) is True
        assert service.mapper.list_sales() == []


def test_summary_includes_fully_sold_symbol() -> None:
    """全部卖光的品种仍要出现，否则用户看不到它的已实现盈亏"""
    with temp_db("soldout.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=950.0,
            )
        )
        summary = service.get_summary()
        assert len(summary.positions) == 1
        assert summary.positions[0].total_grams == 0.0
        assert summary.positions[0].realized_pnl == 500.0
        assert summary.total_realized_pnl == 500.0
        assert summary.total_sold_grams == 10.0


def test_summary_keeps_symbols_separate() -> None:
    with temp_db("multisym.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900, symbol="gds_AUTD"))
        service.mapper.insert_lot(lot("2026-01-01", 5, 800, symbol="hf_XAU"))
        service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                price_per_gram=1000.0,
            )
        )
        summary = service.get_summary()
        by_symbol = {p.symbol: p for p in summary.positions}
        assert by_symbol["gds_AUTD"].total_grams == 0.0
        assert by_symbol["gds_AUTD"].realized_pnl == 1000.0
        assert by_symbol["hf_XAU"].total_grams == 5.0
        assert by_symbol["hf_XAU"].realized_pnl == 0.0


def test_list_sales_fills_realized_pnl() -> None:
    with temp_db("listpnl.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(lot("2026-01-01", 10, 900))
        for grams, price in ((3.0, 1000.0), (2.0, 800.0)):
            service.create_sale(
                SaleRecordCreate(
                    symbol="gds_AUTD", sale_date="2026-02-01", grams=grams,
                    price_per_gram=price,
                )
            )
        rows = service.list_sales()
        assert len(rows) == 2
        assert rows[0].realized_pnl == 300.0  # (1000-900)*3
        assert rows[1].realized_pnl == -200.0  # (800-900)*2


def test_partial_oversell_only_costs_what_was_held() -> None:
    """买 5g 却卖了 8g：只按真正持有的 5g 结转，剩下的记为超卖

    如果按 8g 结转、或把均价当成 0，都会算出一个「凭空多出来的盈利」，
    而且不报错 —— 这是这类账本最容易埋的错。
    """
    lots = [lot("2026-01-01", 5, 900)]
    sales = [sale("2026-02-01", 8, 1000, sale_id=1)]

    result = walk_ledger(build_ledger(lots, sales))
    assert result.sold_grams == 5.0, "只结转 5g"
    assert result.oversold_grams == 3.0
    assert result.realized_pnl == 500.0, "只按 5g 算：(1000-900)*5"
    assert result.grams == 0.0
    assert validate_ledger(lots, sales) is not None


def test_sale_with_no_holdings_at_all_earns_nothing() -> None:
    """完全没有买入记录时有卖出：已实现盈亏必须是 0，不能把卖价全算成利润"""
    position = compute_position(
        "gds_AUTD", [], 950.0, sales=[sale("2026-02-01", 5, 950, sale_id=1)]
    )
    assert position.realized_pnl == 0.0, "无持仓可结转 → 不应凭空产生盈利"
    assert position.total_grams == 0.0
    assert position.total_cost == 0.0
    assert validate_ledger([], [sale("2026-02-01", 5, 950, sale_id=1)]) is not None


def test_buy_and_sell_with_colliding_ids_same_day() -> None:
    """买入 id 与卖出 id 可能撞号（两张表各自的 AUTOINCREMENT）—— 顺序必须仍确定"""
    lots = [lot("2026-01-01", 10, 900, lot_id=7)]
    sales = [sale("2026-01-01", 10, 1000, sale_id=7)]
    events = build_ledger(lots, sales)
    assert [e.kind for e in events] == ["buy", "sell"], "同一天先买后卖"
    position = compute_position("gds_AUTD", lots, 1000.0, sales=sales)
    assert position.realized_pnl == 1000.0
    assert position.total_grams == 0.0


def test_controller_delete_lot_returns_400_not_500() -> None:
    """回归：`delete_lot` 曾经不接 `ValueError`，超卖守卫会变成 500

    守卫本身抛异常是对的，但接口层必须把它翻译成 400 + 人话，
    否则前端只会看到一个「服务器错误」，用户根本不知道自己做错了什么。
    """
    import controller.portfolio_controller as pc

    with temp_db("ctrl.db") as db:
        real_service = pc.service
        pc.service = make_service(db)
        try:
            lot = pc.service.create_lot(
                PurchaseLotCreate(
                    symbol="gds_AUTD", trade_date="2026-01-01",
                    grams=10.0, price_per_gram=900.0,
                )
            )
            pc.service.create_sale(
                SaleRecordCreate(
                    symbol="gds_AUTD", sale_date="2026-02-01", grams=10.0,
                    price_per_gram=950.0,
                )
            )
            response = pc.delete_lot(lot.id)
            assert response.code == 400, f"应为 400，实际 {response.code}"
            assert "超出持仓" in response.message
        finally:
            pc.service = real_service


def test_opening_lot_can_be_sold() -> None:
    """期初持仓也是一条买入记录，所以卖出照样能对上账"""
    with temp_db("opensale.db") as db:
        service = make_service(db)
        service.mapper.insert_lot(
            {**lot("2025-01-01", 30, 900), "is_opening": 1}
        )
        created = service.create_sale(
            SaleRecordCreate(
                symbol="gds_AUTD", sale_date="2026-02-01", grams=12.0,
                price_per_gram=1000.0,
            )
        )
        assert created.realized_pnl == 1200.0
        position = service.get_summary().positions[0]
        assert position.total_grams == 18.0
        assert position.avg_cost == 900.0


if __name__ == "__main__":
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
