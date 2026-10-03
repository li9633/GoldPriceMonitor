"""风险偏好与「期初持仓」测试。

两件事都在修同一类问题：**配置项存得下、读得出，就是没人用**。

- `risk_level` 以前只被读进 `AdvicePrefs` 就没了下文，现在它真的决定止盈/止损阈值
  与单次买入比例；
- `target_position_ratio` 以前同样没人用，而「仓位偏重」actually 由一个硬编码常量
  判定 —— 现在用户设了目标占比就按它判。

「期初持仓」则是为了让人能直接录入「我手里有 30g，均价 900」：底层仍是一条买入记录，
所以持仓成本、止盈止损、分批计划照常工作，但不触发买入回访。

运行
----
    cd backend
    python -m test.test_advice_risk
"""

import contextlib
import os
import sqlite3
import tempfile

from mapper.portfolio_mapper import PortfolioMapper
from models.advice import AdvicePrefs
from service.advice import signals as signal_rules
from service.advice.context import AdviceContext, MarketIndicators, build_plan_states
from service.advice.risk import (
    BASE_POSITION_RATIO_LIMIT_PCT,
    PROFILES,
    position_ratio_limit,
    resolve_risk,
)
from service.advice.strategies import build_advice
from service.position import compute_position, summarize_plans

PRICE = 100.0


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


# ==================== 构造上下文 ====================


def make_indicators(price: float = PRICE, **overrides) -> MarketIndicators:
    base = {
        "current_price": price,
        "avg_24h": price,
        "max_24h": price,
        "min_24h": price,
        "std_24h": price * 0.001,
        "count_24h": 100,
        "volatility_pct": 0.1,
        "trend_6h_direction": "stable",
        "trend_24h_direction": "stable",
    }
    base.update(overrides)
    return MarketIndicators(**base)


def make_lot(price: float, grams: float = 10.0, **overrides) -> dict:
    lot = {
        "id": 1,
        "symbol": "gds_AUTD",
        "trade_date": "2026-01-01",
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
        "channel": "",
        "plan_id": None,
        "is_opening": 0,
    }
    lot.update(overrides)
    return lot


def make_context(
    pnl_pct: float = 0.0,
    prefs: AdvicePrefs | None = None,
    trend: str = "stable",
    price: float = PRICE,
    grams: float = 10.0,
) -> AdviceContext:
    """构造一个浮盈亏恰好为 `pnl_pct` 的持仓上下文"""
    cost = price / (1 + pnl_pct / 100) if pnl_pct != 0 else price
    lots = [make_lot(round(cost, 6), grams=grams)]
    position = compute_position("gds_AUTD", lots, latest_price=price)
    return AdviceContext(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        indicators=make_indicators(price, trend_24h_direction=trend),
        position=position,
        plans=build_plan_states([], summarize_plans([], []), [], __import__("datetime").date(2026, 1, 10)),
        prefs=prefs or AdvicePrefs(),
    )


def ids_of(ctx: AdviceContext) -> set[str]:
    return {signal.id for signal in signal_rules.evaluate(ctx)}


# ==================== 1. 档位表本身 ====================


def test_three_profiles_exist() -> None:
    assert set(PROFILES) == {"conservative", "balanced", "aggressive"}
    assert PROFILES["balanced"].label == "均衡"


def test_unknown_risk_falls_back_to_balanced() -> None:
    """配置脏数据不该让建议生成失败"""
    for bad in (None, "", "  ", "UNKNOWN", "激进", 123):
        assert resolve_risk(bad).key == "balanced", bad
    assert resolve_risk("CONSERVATIVE").key == "conservative", "大小写不敏感"
    assert resolve_risk(" Aggressive ").key == "aggressive", "应去掉空白"


def test_profiles_are_ordered() -> None:
    """保守更早止盈止损、买得更少；进取反之"""
    cons, bal, aggr = (
        PROFILES["conservative"],
        PROFILES["balanced"],
        PROFILES["aggressive"],
    )
    assert cons.profit_pct < bal.profit_pct < aggr.profit_pct
    assert cons.loss_pct > bal.loss_pct > aggr.loss_pct, "亏损阈值的绝对值递增"
    assert cons.deep_loss_pct > bal.deep_loss_pct > aggr.deep_loss_pct
    assert cons.buy_fraction_scale < bal.buy_fraction_scale < aggr.buy_fraction_scale


def test_buy_fraction_is_clamped() -> None:
    aggr = PROFILES["aggressive"]
    assert aggr.buy_fraction(1.0) == 1.0, "不能超过剩余额度"
    assert aggr.buy_fraction(0.5) == 0.7
    assert PROFILES["conservative"].buy_fraction(0.5) == 0.3
    assert PROFILES["balanced"].buy_fraction(0.5) == 0.5


def test_sell_fraction_is_clamped() -> None:
    cons = PROFILES["conservative"]
    assert cons.sell_fraction(1.0, take_profit=False) == 1.0, "不能卖出超过持有量"
    assert cons.sell_fraction(0.5, take_profit=False) == 0.6, "保守止损减得更多"
    assert cons.sell_fraction(0.5, take_profit=True) == 0.6
    aggr = PROFILES["aggressive"]
    assert aggr.sell_fraction(0.5, take_profit=False) == 0.4


# ==================== 2. 风险偏好真的影响信号 ====================


def test_deep_loss_threshold_follows_risk() -> None:
    """-7% 在保守档已算深度浮亏，在均衡/进取档只算普通浮亏"""
    conservative = make_context(-7.0, AdvicePrefs(risk_level="conservative"))
    assert "deep_loss" in ids_of(conservative)

    balanced = make_context(-7.0, AdvicePrefs(risk_level="balanced"))
    assert "deep_loss" not in ids_of(balanced)
    assert "in_loss" in ids_of(balanced), "但仍是浮亏"

    aggressive = make_context(-7.0, AdvicePrefs(risk_level="aggressive"))
    assert "deep_loss" not in ids_of(aggressive), "进取档 -15% 才算深亏"
    assert "in_loss" in ids_of(aggressive), "-7% 已超过进取档 -5% 的浮亏线"

    # -4%：保守/均衡都算浮亏，进取档还没到
    assert "in_loss" in ids_of(
        make_context(-4.0, AdvicePrefs(risk_level="conservative"))
    )
    assert "in_loss" in ids_of(make_context(-4.0, AdvicePrefs(risk_level="balanced")))
    assert "in_loss" not in ids_of(
        make_context(-4.0, AdvicePrefs(risk_level="aggressive"))
    )


def test_profit_threshold_follows_risk() -> None:
    """+6% 在保守档已到止盈线，在均衡/进取档还没到"""
    assert "big_profit" in ids_of(
        make_context(6.0, AdvicePrefs(risk_level="conservative"))
    )
    assert "big_profit" not in ids_of(make_context(6.0, AdvicePrefs(risk_level="balanced")))
    assert "big_profit" not in ids_of(
        make_context(6.0, AdvicePrefs(risk_level="aggressive"))
    )
    # +9% 到了均衡档，但还没到进取档
    assert "big_profit" in ids_of(make_context(9.0, AdvicePrefs(risk_level="balanced")))
    assert "big_profit" not in ids_of(
        make_context(9.0, AdvicePrefs(risk_level="aggressive"))
    )


def test_signal_summary_names_the_profile() -> None:
    """理由里要写清是哪个档位触发的，否则用户不知道为什么 -7% 就报止损"""
    found = signal_rules.evaluate(
        make_context(-7.0, AdvicePrefs(risk_level="conservative"))
    )
    deep = signal_rules.get(found, "deep_loss")
    assert "保守" in deep.summary
    assert "-6" in deep.summary
    assert deep.metrics["risk_level"] == "conservative"


def test_stop_loss_uses_risk_threshold_in_rationale() -> None:
    ctx = make_context(
        -7.0, AdvicePrefs(risk_level="conservative"), trend="down"
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action.value == "STOP_LOSS"
    assert "保守" in draft.rationale
    assert "-6" in draft.rationale


# ==================== 3. 目标持仓占比真的生效 ====================


def test_position_ratio_limit_uses_user_target() -> None:
    class RatioStub:
        def __init__(self, value: float) -> None:
            self.target_position_ratio = value

    assert position_ratio_limit(AdvicePrefs()) == BASE_POSITION_RATIO_LIMIT_PCT
    assert position_ratio_limit(AdvicePrefs(target_position_ratio=50.0)) == 50.0
    # 0 与负数都视为「未设置」（模型本身已禁止负数，这里防的是脏数据）
    assert position_ratio_limit(RatioStub(0.0)) == BASE_POSITION_RATIO_LIMIT_PCT
    assert position_ratio_limit(RatioStub(-1.0)) == BASE_POSITION_RATIO_LIMIT_PCT


def test_position_ratio_high_respects_target() -> None:
    """持仓 1000 元市值：总资金 1250 → 占比 80%"""
    # 默认上限 100% → 不报
    loose = make_context(0.0, AdvicePrefs(total_investable=1250.0))
    assert abs(loose.position_ratio_pct() - 80.0) < 0.01
    assert "position_ratio_high" not in ids_of(loose)

    # 用户把目标占比设成 50% → 80% 超了，要提醒
    strict = make_context(
        0.0, AdvicePrefs(total_investable=1250.0, target_position_ratio=50.0)
    )
    found = signal_rules.evaluate(strict)
    assert "position_ratio_high" in {s.id for s in found}
    high = signal_rules.get(found, "position_ratio_high")
    assert "50" in high.summary, "理由里要说明是按用户设的上限判的"
    assert high.metrics["position_ratio_limit"] == 50.0
    assert high.metrics["position_ratio_pct"] == 80.0


# ==================== 4. 买卖数量随风险偏好变化 ====================


def test_buy_grams_scale_with_risk() -> None:
    from service.advice.strategies.common import suggest_buy_grams

    results = {}
    for level in ("conservative", "balanced", "aggressive"):
        ctx = make_context(0.0, AdvicePrefs(risk_level=level, target_grams=100.0))
        results[level] = suggest_buy_grams(ctx, fraction=0.5)

    assert results["conservative"] < results["balanced"] < results["aggressive"]
    # 剩余额度 100 - 10 = 90；比例 0.5 再按档位缩放（0.6 / 1.0 / 1.4）
    assert results["conservative"] == 27.0
    assert results["balanced"] == 45.0
    assert results["aggressive"] == 63.0


def test_sell_grams_scale_with_risk() -> None:
    from service.advice.strategies.common import suggest_sell_grams

    ctx_c = make_context(0.0, AdvicePrefs(risk_level="conservative"))
    ctx_a = make_context(0.0, AdvicePrefs(risk_level="aggressive"))
    # 持仓 10g，止损比例 0.5
    assert suggest_sell_grams(ctx_c, 0.5) == 6.0
    assert suggest_sell_grams(ctx_a, 0.5) == 4.0
    # 止盈比例 1/3
    assert suggest_sell_grams(ctx_c, 1 / 3, take_profit=True) == round(10 * 0.4, 4)
    assert suggest_sell_grams(ctx_a, 1 / 3, take_profit=True) == round(10 * 1 / 3 * 0.8, 4)


def test_take_profit_grams_follow_risk() -> None:
    cons = make_context(6.0, AdvicePrefs(risk_level="conservative"))
    draft = build_advice(cons, signal_rules.evaluate(cons))
    assert draft.action.value == "TAKE_PROFIT"
    assert draft.target_grams == 4.0, "保守档止盈落袋更多（10g × 1/3 × 1.2）"
    assert "保守" in draft.rationale


# ==================== 5. 期初持仓 ====================


def test_opening_column_in_schema_and_migration() -> None:
    with temp_db("legacy_portfolio.db") as db:
        # 造一个「旧版」表结构（没有 is_opening）
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE purchase_lots ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, "
            "trade_date TEXT NOT NULL, grams REAL NOT NULL, "
            "price_per_gram REAL NOT NULL, fee REAL NOT NULL DEFAULT 0, "
            "channel TEXT NOT NULL DEFAULT '', plan_id INTEGER NULL, "
            "note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        mapper = PortfolioMapper(db_file=db)  # init_tables 应完成迁移
        columns = {
            row[1]
            for row in sqlite3.connect(db).execute("PRAGMA table_info(purchase_lots)")
        }
        assert "is_opening" in columns

        lot_id = mapper.insert_lot(
            {
                "symbol": "gds_AUTD",
                "trade_date": "2025-01-01",
                "grams": 30.0,
                "price_per_gram": 900.0,
                "is_opening": True,
            }
        )
        assert mapper.get_lot(lot_id)["is_opening"] == 1

        # 迁移应可重复执行
        PortfolioMapper(db_file=db)
        assert mapper.get_lot(lot_id)["is_opening"] == 1


def test_opening_defaults_to_zero() -> None:
    with temp_db("default_portfolio.db") as db:
        mapper = PortfolioMapper(db_file=db)
        lot_id = mapper.insert_lot(
            {
                "symbol": "gds_AUTD",
                "trade_date": "2025-01-01",
                "grams": 10.0,
                "price_per_gram": 900.0,
            }
        )
        assert mapper.get_lot(lot_id)["is_opening"] == 0


def test_opening_lot_counts_toward_position() -> None:
    """期初持仓必须计入成本与市值，否则整个产品对老持仓用户无效"""
    lots = [make_lot(900.0, grams=30.0, is_opening=1)]
    position = compute_position("gds_AUTD", lots, latest_price=950.0)
    assert position.total_grams == 30.0
    assert position.avg_cost == 900.0
    assert round(position.unrealized_pnl_pct, 2) == 5.56


def test_opening_lot_does_not_fill_a_plan() -> None:
    """期初持仓不该顶替任何购买计划的批次（靠 plan_id 为空天然隔离）"""
    plan = {"id": 7, "symbol": "gds_AUTD", "target_grams": 50.0, "tranches": 5}
    lots = [
        make_lot(900.0, grams=30.0, is_opening=1, plan_id=None),
        make_lot(910.0, grams=10.0, id=2, plan_id=7),
    ]
    progress = summarize_plans([plan], lots)[0]
    assert progress.filled_grams == 10.0, "只算归属该计划的批次"
    assert progress.filled_tranches == 1


def test_opening_lot_skips_purchase_followup() -> None:
    """期初持仓不触发买入回访 —— 否则一录入持仓就被回访"""
    import datetime

    from mapper.advice_mapper import AdviceMapper
    from service.advice.advice_engine import AdviceEngine

    class FakeLotMapper:
        def __init__(self, lots):
            self.lots = list(lots)

        def list_lots(self, symbol=None):
            return list(self.lots)

    at = datetime.datetime(2026, 1, 20, 10, 0)
    yesterday = (at.date() - datetime.timedelta(days=1)).isoformat()

    # 直接构造引擎：`pending_reviews` 只用到这两个 mapper
    engine = object.__new__(AdviceEngine)
    with temp_db("followup.db") as db:
        engine.advice_mapper = AdviceMapper(db_file=db)

        engine.portfolio_mapper = FakeLotMapper(
            [make_lot(900.0, trade_date=yesterday, is_opening=1)]
        )
        assert engine.pending_reviews(at) == []

        # 同一日期、非期初的买入仍然会被回访
        engine.portfolio_mapper = FakeLotMapper(
            [make_lot(900.0, trade_date=yesterday)]
        )
        assert [item[1] for item in engine.pending_reviews(at)] == [1]


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
