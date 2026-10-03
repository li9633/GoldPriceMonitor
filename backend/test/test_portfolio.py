"""持仓域测试：纯计算 + 持久化 + 服务编排。

覆盖 `docs/refactor-plan.md` §3 的领域模型与 §2 锁定的成本口径：
统一按「克」，手续费只记录、不摊入成本。

运行
----
    cd backend
    python -m test.test_portfolio
"""

import contextlib
import os
import tempfile

from pydantic import ValidationError

from mapper.portfolio_mapper import PortfolioMapper
from models.portfolio import (
    PurchaseLotCreate,
    PurchaseLotResponse,
    PurchaseLotUpdate,
    PurchasePlanCreate,
    PurchasePlanUpdate,
)
from service.portfolio_service import PortfolioService
from service.position import (
    compute_plan_progress,
    compute_position,
    summarize_totals,
)


@contextlib.contextmanager
def assert_raises(exc_type: type[BaseException], match: str | None = None):
    """本项目没有引入 pytest，这里用标准库实现 `pytest.raises` 的最小等价物"""
    try:
        yield
    except exc_type as exc:
        if match is not None and match not in str(exc):
            raise AssertionError(f"异常信息中不含 {match!r}：{exc}") from exc
    else:
        raise AssertionError(f"未按预期抛出 {exc_type.__name__}")


def approx(actual: float, expected: float, tol: float = 1e-6) -> bool:
    return abs(actual - expected) <= tol


@contextlib.contextmanager
def temp_db(name: str):
    """每个用例一个干净的库文件（WAL 的 -wal/-shm 也要一并清掉）"""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, name)
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(base + suffix):
                os.remove(base + suffix)
        yield base


def lot(
    grams: float,
    price: float,
    fee: float = 0.0,
    trade_date: str = "2026-01-05",
    symbol: str = "gds_AUTD",
    plan_id: int | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "grams": grams,
        "price_per_gram": price,
        "fee": fee,
        "plan_id": plan_id,
    }


# ==================== 1. 持仓计算（纯函数） ====================


def test_position_empty_lots() -> None:
    position = compute_position("gds_AUTD", [], 900.0)
    assert position.total_grams == 0
    assert position.total_cost == 0
    assert position.avg_cost == 0
    assert position.lot_count == 0
    assert position.market_value is None, "没有持仓时不应编造市值"
    assert position.first_trade_date is None


def test_position_single_lot() -> None:
    position = compute_position("gds_AUTD", [lot(10, 900.0)], 950.0)
    assert position.lot_count == 1
    assert position.total_grams == 10
    assert position.total_cost == 9000.0
    assert position.avg_cost == 900.0
    assert position.market_value == 9500.0
    assert position.unrealized_pnl == 500.0
    assert approx(position.unrealized_pnl_pct, 5.56, 0.01)


def test_position_weighted_average_across_lots() -> None:
    """10 克 @900 + 30 克 @1000 → 均价 (9000+30000)/40 = 975"""
    lots = [lot(10, 900.0), lot(30, 1000.0)]
    position = compute_position("gds_AUTD", lots, 1000.0)
    assert position.total_grams == 40
    assert position.total_cost == 39000.0
    assert position.avg_cost == 975.0
    assert position.market_value == 40000.0
    assert position.unrealized_pnl == 1000.0


def test_position_fee_is_recorded_but_not_amortized() -> None:
    """成本口径：手续费只记录，不摊入成本价"""
    position = compute_position("gds_AUTD", [lot(10, 900.0, fee=25.0)], 900.0)
    assert position.total_cost == 9000.0, "手续费不应计入成本"
    assert position.avg_cost == 900.0
    assert position.total_fee == 25.0, "手续费应单独可见"
    # 按成本价卖出时盈亏为 0，而不是被手续费扭曲
    assert position.unrealized_pnl == 0.0


def test_position_without_price_returns_none_metrics() -> None:
    """拿不到行情时必须是 None，不能是 0 —— 0 会被读成「刚好持平」"""
    position = compute_position("gds_AUTD", [lot(10, 900.0)], None)
    assert position.total_grams == 10
    assert position.total_cost == 9000.0
    assert position.latest_price is None
    assert position.market_value is None
    assert position.unrealized_pnl is None
    assert position.unrealized_pnl_pct is None


def test_position_trade_date_range() -> None:
    lots = [
        lot(5, 900.0, trade_date="2026-03-10"),
        lot(5, 910.0, trade_date="2025-12-01"),
        lot(5, 920.0, trade_date="2026-01-20"),
    ]
    position = compute_position("gds_AUTD", lots, 900.0)
    assert position.first_trade_date == "2025-12-01"
    assert position.last_trade_date == "2026-03-10"


# ==================== 2. 计划进度 ====================


def test_plan_progress_partial_fill() -> None:
    plan = {"id": 1, "symbol": "gds_AUTD", "target_grams": 100.0, "tranches": 4,
            "status": "active", "start_date": "2026-01-01", "end_date": None}
    lots = [lot(20, 900.0, plan_id=1), lot(20, 910.0, plan_id=1)]
    progress = compute_plan_progress(plan, lots)
    assert progress.filled_grams == 40
    assert progress.remaining_grams == 60
    assert progress.progress_pct == 40.0
    assert progress.filled_tranches == 2
    assert progress.invested_amount == 36200.0
    assert progress.avg_cost == 905.0


def test_plan_progress_complete_and_overbuy() -> None:
    plan = {"id": 1, "symbol": "gds_AUTD", "target_grams": 100.0, "tranches": 4,
            "status": "done"}
    complete = compute_plan_progress(plan, [lot(100, 900.0, plan_id=1)])
    assert complete.progress_pct == 100.0
    assert complete.remaining_grams == 0

    over = compute_plan_progress(plan, [lot(130, 900.0, plan_id=1)])
    assert over.progress_pct == 130.0, "超买时进度可以大于 100，由展示层决定怎么呈现"
    assert over.remaining_grams == 0, "剩余克数不应为负"


def test_plan_progress_ignores_unlinked_lots() -> None:
    plan = {"id": 1, "symbol": "gds_AUTD", "target_grams": 100.0, "tranches": 4,
            "status": "active"}
    lots = [lot(20, 900.0, plan_id=1), lot(50, 900.0, plan_id=None)]
    progress = compute_plan_progress(plan, lots)
    assert progress.filled_grams == 20
    assert progress.filled_tranches == 1


# ==================== 3. 合计 ====================


def test_totals_all_priced() -> None:
    positions = [
        compute_position("gds_AUTD", [lot(10, 900.0)], 1000.0),
        compute_position("hf_XAU", [lot(5, 800.0, symbol="hf_XAU")], 900.0),
    ]
    totals = summarize_totals(positions)
    assert totals["total_grams"] == 15
    assert totals["total_cost"] == 13000.0
    assert totals["total_market_value"] == 14500.0
    assert totals["total_unrealized_pnl"] == 1500.0
    assert totals["priced_symbols"] == ["gds_AUTD", "hf_XAU"]


def test_totals_with_unpriced_symbol_is_none() -> None:
    """任一品种没有行情时，合计市值返回 None，不静默少算"""
    positions = [
        compute_position("gds_AUTD", [lot(10, 900.0)], 1000.0),
        compute_position("hf_XAU", [lot(5, 800.0, symbol="hf_XAU")], None),
    ]
    totals = summarize_totals(positions)
    assert totals["total_market_value"] is None
    assert totals["total_unrealized_pnl"] is None
    assert totals["total_cost"] == 13000.0, "成本仍应可见"
    assert totals["priced_symbols"] == ["gds_AUTD"]


# ==================== 4. 持久化 ====================


def test_lot_crud_roundtrip() -> None:
    with temp_db("crud.db") as db:
        mapper = PortfolioMapper(db_file=db)
        assert mapper.list_lots() == []

        lot_id = mapper.insert_lot(lot(10, 905.5, fee=12.0, trade_date="2026-02-02"))
        assert lot_id > 0

        stored = mapper.get_lot(lot_id)
        assert stored is not None
        assert stored["grams"] == 10
        assert stored["price_per_gram"] == 905.5
        assert stored["fee"] == 12.0
        assert stored["trade_date"] == "2026-02-02"
        assert stored["created_at"], "created_at 应自动写入"

        assert mapper.update_lot(lot_id, {"grams": 12.0, "note": "补记"}) is True
        updated = mapper.get_lot(lot_id)
        assert updated["grams"] == 12.0
        assert updated["note"] == "补记"
        assert updated["price_per_gram"] == 905.5, "未指定的字段不应被覆盖"

        assert mapper.delete_lot(lot_id) is True
        assert mapper.get_lot(lot_id) is None
        assert mapper.delete_lot(lot_id) is False, "重复删除应返回 False"


def test_lots_ordered_by_trade_date() -> None:
    with temp_db("order.db") as db:
        mapper = PortfolioMapper(db_file=db)
        mapper.insert_lot(lot(1, 900.0, trade_date="2026-03-01"))
        mapper.insert_lot(lot(1, 901.0, trade_date="2025-11-15"))
        mapper.insert_lot(lot(1, 902.0, trade_date="2026-01-09"))

        dates = [row["trade_date"] for row in mapper.list_lots()]
        assert dates == ["2025-11-15", "2026-01-09", "2026-03-01"]


def test_lot_symbol_filter() -> None:
    with temp_db("filter.db") as db:
        mapper = PortfolioMapper(db_file=db)
        mapper.insert_lot(lot(1, 900.0, symbol="gds_AUTD"))
        mapper.insert_lot(lot(2, 800.0, symbol="hf_XAU"))

        assert len(mapper.list_lots()) == 2
        only_autd = mapper.list_lots("gds_AUTD")
        assert len(only_autd) == 1
        assert only_autd[0]["symbol"] == "gds_AUTD"


def test_plan_crud_and_policy_roundtrip() -> None:
    with temp_db("plans.db") as db:
        mapper = PortfolioMapper(db_file=db)
        plan_id = mapper.insert_plan(
            {
                "symbol": "gds_AUTD",
                "target_grams": 100.0,
                "budget": 90000.0,
                "tranches": 4,
                "tranche_grams": 25.0,
                "trigger_policy": {"type": "drop_pct", "pct": 1.0},
                "start_date": "2026-01-01",
                "status": "active",
            }
        )
        stored = mapper.get_plan(plan_id)
        assert stored is not None
        assert stored["trigger_policy"] == {"type": "drop_pct", "pct": 1.0}
        assert stored["tranches"] == 4
        assert stored["updated_at"]

        assert mapper.update_plan(plan_id, {"status": "paused"}) is True
        assert mapper.get_plan(plan_id)["status"] == "paused"

        assert [p["id"] for p in mapper.list_plans(status="paused")] == [plan_id]
        assert mapper.list_plans(status="active") == []

        assert mapper.delete_plan(plan_id) is True
        assert mapper.get_plan(plan_id) is None


def test_delete_plan_keeps_lots_and_clears_link() -> None:
    """删计划不应该删掉买入记录，只把关联置空"""
    with temp_db("cascade.db") as db:
        mapper = PortfolioMapper(db_file=db)
        plan_id = mapper.insert_plan(
            {"symbol": "gds_AUTD", "target_grams": 50.0, "tranches": 2}
        )
        lot_id = mapper.insert_lot(lot(10, 900.0, plan_id=plan_id))
        mapper.insert_lot(lot(5, 910.0, plan_id=None))

        assert mapper.delete_plan(plan_id) is True

        kept = mapper.get_lot(lot_id)
        assert kept is not None, "买入记录必须保留"
        assert kept["plan_id"] is None, "关联应被置空"
        assert len(mapper.list_lots()) == 2


def test_malformed_policy_json_degrades_gracefully() -> None:
    with temp_db("badjson.db") as db:
        mapper = PortfolioMapper(db_file=db)
        plan_id = mapper.insert_plan(
            {"symbol": "gds_AUTD", "target_grams": 10.0, "tranches": 1}
        )
        # 直接写入非法 JSON，模拟手工改库
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE purchase_plans SET trigger_policy = ? WHERE id = ?",
            ("{not json", plan_id),
        )
        conn.commit()
        conn.close()

        stored = mapper.get_plan(plan_id)
        assert stored["trigger_policy"] == {}, "非法 JSON 应降级为空字典而不是抛异常"


# ==================== 5. 服务编排 ====================


class FakePriceMapper:
    def __init__(self, prices: dict[str, float | None]) -> None:
        self.prices = prices
        self.asked: list[str] = []

    def get_latest_price(self, symbol: str) -> float | None:
        self.asked.append(symbol)
        return self.prices.get(symbol)


def make_service(db: str, prices: dict[str, float | None]) -> PortfolioService:
    service = object.__new__(PortfolioService)
    service.mapper = PortfolioMapper(db_file=db)
    service.price_mapper = FakePriceMapper(prices)
    return service


def test_service_creates_and_lists_lots() -> None:
    with temp_db("service.db") as db:
        service = make_service(db, {"gds_AUTD": 950.0})
        created = service.create_lot(
            PurchaseLotCreate(
                symbol="gds_AUTD",
                trade_date="2026-01-05",
                grams=10.0,
                price_per_gram=900.0,
                fee=5.0,
                channel="银行积存金",
            )
        )
        assert created.id > 0
        assert created.amount == 9000.0, "amount 是克数 × 单价的派生字段"

        listed = service.list_lots()
        assert len(listed) == 1
        assert listed[0].channel == "银行积存金"


def test_service_rejects_unknown_plan() -> None:
    with temp_db("badplan.db") as db:
        service = make_service(db, {})
        with assert_raises(ValueError, match="不存在"):
            service.create_lot(
                PurchaseLotCreate(
                    symbol="gds_AUTD",
                    trade_date="2026-01-05",
                    grams=10.0,
                    price_per_gram=900.0,
                    plan_id=999,
                )
            )


def test_service_update_and_delete_missing_lot() -> None:
    with temp_db("missing.db") as db:
        service = make_service(db, {})
        assert service.update_lot(4242, PurchaseLotUpdate(grams=1.0)) is None
        assert service.delete_lot(4242) is False


def test_service_update_only_touches_given_fields() -> None:
    with temp_db("partial.db") as db:
        service = make_service(db, {})
        created = service.create_lot(
            PurchaseLotCreate(
                symbol="gds_AUTD",
                trade_date="2026-01-05",
                grams=10.0,
                price_per_gram=900.0,
                channel="金店",
            )
        )
        updated = service.update_lot(created.id, PurchaseLotUpdate(note="改一下"))
        assert updated is not None
        assert updated.note == "改一下"
        assert updated.grams == 10.0
        assert updated.channel == "金店", "未传的字段必须保持原值"


def test_service_summary_uses_latest_price() -> None:
    with temp_db("summary.db") as db:
        service = make_service(db, {"gds_AUTD": 1000.0, "hf_XAU": None})
        service.create_lot(
            PurchaseLotCreate(
                symbol="gds_AUTD",
                trade_date="2026-01-05",
                grams=10.0,
                price_per_gram=900.0,
            )
        )
        service.create_lot(
            PurchaseLotCreate(
                symbol="hf_XAU",
                trade_date="2026-01-06",
                grams=5.0,
                price_per_gram=800.0,
            )
        )

        summary = service.get_summary()
        assert [p.symbol for p in summary.positions] == ["gds_AUTD", "hf_XAU"]
        autd = next(p for p in summary.positions if p.symbol == "gds_AUTD")
        assert autd.market_value == 10000.0
        assert autd.unrealized_pnl == 1000.0

        # hf_XAU 没有行情 → 合计市值返回 None，而不是只算一半
        assert summary.total_cost == 13000.0
        assert summary.total_market_value is None
        assert summary.priced_symbols == ["gds_AUTD"]


def test_service_summary_includes_plan_progress() -> None:
    with temp_db("summary_plan.db") as db:
        service = make_service(db, {"gds_AUTD": 950.0})
        plan = service.create_plan(
            PurchasePlanCreate(
                symbol="gds_AUTD", target_grams=100.0, tranches=4,
                trigger_policy={"type": "interval", "days": 7},
            )
        )
        service.create_lot(
            PurchaseLotCreate(
                symbol="gds_AUTD",
                trade_date="2026-01-05",
                grams=25.0,
                price_per_gram=900.0,
                plan_id=plan.id,
            )
        )

        summary = service.get_summary()
        assert len(summary.plans) == 1
        progress = summary.plans[0]
        assert progress.plan_id == plan.id
        assert progress.filled_grams == 25.0
        assert progress.progress_pct == 25.0
        assert progress.filled_tranches == 1


def test_service_empty_portfolio() -> None:
    with temp_db("empty.db") as db:
        service = make_service(db, {})
        summary = service.get_summary()
        assert summary.positions == []
        assert summary.plans == []
        assert summary.total_grams == 0
        assert summary.total_market_value is None


# ==================== 6. 入参校验 ====================


def test_model_rejects_bad_date() -> None:
    with assert_raises(ValidationError, match="YYYY-MM-DD"):
        PurchaseLotCreate(
            symbol="gds_AUTD",
            trade_date="2026/01/05",
            grams=10.0,
            price_per_gram=900.0,
        )


def test_model_rejects_non_positive_grams() -> None:
    with assert_raises(ValidationError):
        PurchaseLotCreate(
            symbol="gds_AUTD", trade_date="2026-01-05", grams=0.0, price_per_gram=900.0
        )


def test_model_rejects_bad_plan_status() -> None:
    with assert_raises(ValidationError, match="状态"):
        PurchasePlanCreate(symbol="gds_AUTD", target_grams=10.0, status="unknown")


def test_lot_response_amount_is_derived() -> None:
    response = PurchaseLotResponse(
        id=1,
        symbol="gds_AUTD",
        trade_date="2026-01-05",
        grams=1.333,
        price_per_gram=900.0,
    )
    assert response.amount == 1199.7


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
