"""通知阶段 B：行情口径切换（MarketView）测试。

INTL_ONLY（SGE 休市、国际金开市）时：

1. 建议的**主体**不变（持仓 / 计划挂在主品种上）；
2. 指标快照、估值价、推送节流比较基准全部切到国际金折算价；
3. 消息携带估值说明（可能与国内开盘价存在偏差）；
4. evidence 记录 `market_view` 供追溯；
5. 正常时段与「无国际金数据」时回落到主品种口径。

运行
----
    cd backend
    python -m test.test_market_view
"""

from service.advice.advice_engine import AdviceEngine
from service.advice.context import AdviceContext
from test.test_monitor_send_gate import (
    HOLIDAY,
    WED,
    FakeAdviceEngine,
    FakeNotificationService,
    frozen_monitor,
    make_draft,
    make_monitor,
)
from utils.market_session import SendPolicy

LONDON = {"price": 2330.0, "converted_cny_price": 540.0}
SGE_PRICE = 900.0


# ==================== 引擎层：build_context 口径 ====================


class FakeSnapshot:
    """带标记的假快照：count_24h 用来区分数据来自哪个品种"""

    def __init__(self, tag: str, count: int) -> None:
        self.tag = tag
        self._count = count

    def statistics(self, _hours: int) -> dict:
        return {"avg": 1.0, "max": 2.0, "min": 0.5, "std": 0.1, "count": self._count}

    def ma(self, _n: int) -> float:
        return 1.0

    def trend(self, _n: int) -> dict:
        return {"slope": 0.1, "direction": "up"}

    min_3m = 0.5
    min_6m = 0.5

    def prices_last_n(self, _n: int) -> list[float]:
        return [1.0]


class StubPriceMapper:
    def __init__(self) -> None:
        self.snapshots: dict[str, FakeSnapshot] = {}
        self.requested: list[str] = []

    def get_check_snapshot(self, symbol: str):
        self.requested.append(symbol)
        return self.snapshots.get(symbol)


class StubPortfolioMapper:
    def list_lots(self, _symbol):
        return []

    def list_sales(self, _symbol):
        return []

    def list_plans(self, _symbol):
        return []


class StubEntryEvaluator:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def evaluate(self, symbol: str, _price: float):
        self.requested.append(symbol)
        return None


def make_engine() -> tuple[AdviceEngine, StubPriceMapper, StubEntryEvaluator]:
    engine = AdviceEngine()
    price_mapper = StubPriceMapper()
    entry = StubEntryEvaluator()
    engine.price_mapper = price_mapper
    engine.portfolio_mapper = StubPortfolioMapper()
    engine.entry_evaluator = entry
    return engine, price_mapper, entry


def test_build_context_uses_market_symbol_snapshot() -> None:
    """market_symbol=hf_XAU：指标来自国际金快照，主体与持仓查询仍是主品种"""
    engine, price_mapper, entry = make_engine()
    price_mapper.snapshots = {
        "gds_AUTD": FakeSnapshot("sge", count=7),
        "hf_XAU": FakeSnapshot("intl", count=100),
    }

    ctx = engine.build_context(
        "gds_AUTD", 540.0, market_symbol="hf_XAU", with_entry_strategy=True
    )

    assert isinstance(ctx, AdviceContext)
    assert ctx.symbol == "gds_AUTD", "建议主体不变"
    assert ctx.market_symbol == "hf_XAU"
    assert ctx.indicators.count_24h == 100, "指标应来自国际金快照"
    assert price_mapper.requested == ["hf_XAU"], "不应再取 SGE 快照"
    assert entry.requested == ["hf_XAU"], "建仓回测也应按口径品种"


def test_build_context_defaults_to_main_symbol() -> None:
    """不传 market_symbol：行为与改造前一致"""
    engine, price_mapper, entry = make_engine()
    price_mapper.snapshots = {"gds_AUTD": FakeSnapshot("sge", count=7)}

    ctx = engine.build_context("gds_AUTD", SGE_PRICE, with_entry_strategy=True)

    assert ctx.market_symbol is None
    assert ctx.indicators.count_24h == 7
    assert price_mapper.requested == ["gds_AUTD"]
    assert entry.requested == ["gds_AUTD"]


def test_evidence_records_market_view() -> None:
    """evidence 记录口径品种；默认口径记为主体品种"""
    engine, price_mapper, _entry = make_engine()
    price_mapper.snapshots = {
        "gds_AUTD": FakeSnapshot("sge", count=7),
        "hf_XAU": FakeSnapshot("intl", count=100),
    }

    intl_ctx = engine.build_context("gds_AUTD", 540.0, market_symbol="hf_XAU")
    assert intl_ctx.to_evidence()["market_view"] == "hf_XAU"

    normal_ctx = engine.build_context("gds_AUTD", SGE_PRICE)
    assert normal_ctx.to_evidence()["market_view"] == "gds_AUTD"


# ==================== 监控层：INTL_ONLY 接线 ====================


def test_intl_only_switches_market_view() -> None:
    """国庆假期（INTL_ONLY）：评估价与口径切到国际金折算价"""
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)
    prices_data = {"gds_AUTD": {"price": SGE_PRICE}, "hf_XAU": LONDON}

    with frozen_monitor(HOLIDAY):
        decision = monitor.send_gate.policy_decision()
        assert decision.policy is SendPolicy.INTL_ONLY
        monitor._advise(prices_data, SGE_PRICE, decision)

    assert engine.compute_calls == 1
    assert engine.last_compute["market_symbol"] == "hf_XAU"
    assert engine.last_compute["price"] == 540.0, "评估价应为国际金折算价"
    assert engine.last_compute["symbol"] == "gds_AUTD", "主体品种不变"


def test_intl_only_push_carries_intl_price_and_note() -> None:
    """假期推送：消息价格为国际金折算价，且带估值说明"""
    from models.advice import AdviceAction

    engine = FakeAdviceEngine(make_draft(AdviceAction.BUY_PARTIAL))
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)
    prices_data = {"gds_AUTD": {"price": SGE_PRICE}, "hf_XAU": LONDON}

    with frozen_monitor(HOLIDAY):
        decision = monitor.send_gate.policy_decision()
        monitor._advise(prices_data, SGE_PRICE, decision)

    assert notifier.sent, "首次评估应推送"
    sent = notifier.sent[0]
    assert sent["price"] == 540.0
    assert "偏差" in sent["extra_info"]["valuation_note"]


def test_normal_period_keeps_main_symbol() -> None:
    """交易日（NORMAL）：口径与价格不变"""
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)
    prices_data = {"gds_AUTD": {"price": SGE_PRICE}, "hf_XAU": LONDON}

    with frozen_monitor(WED):
        decision = monitor.send_gate.policy_decision()
        assert decision.policy is SendPolicy.NORMAL
        monitor._advise(prices_data, SGE_PRICE, decision)

    assert engine.last_compute["market_symbol"] is None
    assert engine.last_compute["price"] == SGE_PRICE


def test_intl_only_without_london_data_falls_back() -> None:
    """假期但国际金数据缺失：回落主品种口径（价格冻结，由去重兜底）"""
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)
    prices_data = {"gds_AUTD": {"price": SGE_PRICE}}

    with frozen_monitor(HOLIDAY):
        decision = monitor.send_gate.policy_decision()
        monitor._advise(prices_data, SGE_PRICE, decision)

    assert engine.last_compute["market_symbol"] is None
    assert engine.last_compute["price"] == SGE_PRICE


def test_intl_only_dedup_uses_intl_price() -> None:
    """假期内重复评估：去重冷却按国际金价格判定（价格不变 → 抑制）"""
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)
    prices_data = {"gds_AUTD": {"price": SGE_PRICE}, "hf_XAU": LONDON}

    with frozen_monitor(HOLIDAY):
        decision = monitor.send_gate.policy_decision()
        monitor._advise(prices_data, SGE_PRICE, decision)
        monitor._advice_timer.reset()  # 绕过评估节流，直接验证去重
        monitor._advise(prices_data, SGE_PRICE, decision)

    assert engine.saved, "第二次评估应被去重抑制"
    status, reason = engine.saved[-1]
    assert status == "suppressed" and reason == "duplicate"


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
