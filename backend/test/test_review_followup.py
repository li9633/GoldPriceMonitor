"""买入后 T+1/T+7/T+30 复盘测试（阶段 4 事件回访）。

重点覆盖三件事：

1. **触发时机**：只在「买入日期 + N 天」附近触发。否则用户补录一笔三个月前的买入，
   会被一次性补出三条复盘 —— 补录历史等于被轰炸。
2. **不重复**：`has_review` 保证每笔买入每档只出一条；被闸门拦下的不算，
   下一次巡检仍会重试（否则那条复盘就永远丢了）。
3. **动作一致**：复盘的动作沿用常规判断，不自己另起一套 —— 否则会出现
   「复盘说补仓、常规建议说观望」。

运行
----
    cd backend
    python -m test.test_review_followup
"""

import contextlib
import datetime
import logging
import os
import sqlite3
import tempfile

import service.monitor_service as monitor_module
from mapper.advice_mapper import AdviceMapper
from models.advice import (
    AdviceAction,
    AdviceDraft,
    AdviceKind,
    AdvicePrefs,
    AdviceRecord,
    AdviceStatus,
)
from service.advice import signals as signal_rules
from service.advice.advice_engine import (
    FOLLOWUP_CATCHUP_DAYS,
    FOLLOWUP_HORIZONS,
    AdviceEngine,
    ComputedAdvice,
)
from service.advice.context import AdviceContext, MarketIndicators, build_plan_states
from service.advice.strategies import build_advice, build_regular, select_kind
from service.monitor_service import FOLLOWUP_REVIEW_SECONDS, MonitorService
from service.position import compute_position, summarize_plans
from service.send_gate import GateDecision, SendGate
from utils.due_timer import DueTimer
from utils.market_session import SendPolicy, Session

_test_logger = logging.getLogger("test.followup")
_test_logger.addHandler(logging.NullHandler())
_test_logger.propagate = False

TODAY = datetime.date(2026, 1, 20)
NOW = datetime.datetime(2026, 1, 20, 10, 0)


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


@contextlib.contextmanager
def frozen(at: datetime.datetime):
    """冻结监控循环与去重各自的 now 绑定"""
    import service.send_gate as send_gate_module

    saved_monitor = monitor_module.now
    saved_gate = send_gate_module.now
    monitor_module.now = lambda: at
    send_gate_module.now = lambda: at
    try:
        yield
    finally:
        monitor_module.now = saved_monitor
        send_gate_module.now = saved_gate


# ==================== 测试替身 ====================


class FakeLotMapper:
    def __init__(self, lots, sales=None):
        self.lots = list(lots)
        self.sales = list(sales or [])

    def list_lots(self, symbol=None):
        return [row for row in self.lots if symbol is None or row["symbol"] == symbol]

    def list_sales(self, symbol=None):
        return [row for row in self.sales if symbol is None or row["symbol"] == symbol]

    def list_plans(self, symbol=None, status=None):
        return []


class FakeSettings:
    def get_advice_config(self):
        return {}

    def get_alert_config(self):
        return {}

    def get_monitor_config(self):
        return {"main_symbol": "gds_AUTD"}

    def get_symbol_name_map(self):
        return {"gds_AUTD": "黄金T+D"}


class FakeSnapshotPriceMapper:
    """复盘测试只关心「这笔买入」的交代，行情快照给 None 即可"""

    def get_check_snapshot(self, symbol):
        return None

    def get_latest_price(self, symbol):
        return None

    def get_price_near(self, symbol, timestamp):
        return None


def make_engine(db: str, lots: list[dict]) -> AdviceEngine:
    engine = object.__new__(AdviceEngine)
    engine.advice_mapper = AdviceMapper(db_file=db)
    engine.portfolio_mapper = FakeLotMapper(lots)
    engine.settings = FakeSettings()
    engine.entry_evaluator = _NoEntryEvaluator()
    engine.price_mapper = FakeSnapshotPriceMapper()
    return engine


class _NoEntryEvaluator:
    def evaluate(self, symbol, current_price, **kwargs):
        return None


def lot(
    lot_id: int,
    trade_date: str,
    grams: float = 10.0,
    price: float = 900.0,
    symbol: str = "gds_AUTD",
) -> dict:
    return {
        "id": lot_id,
        "symbol": symbol,
        "trade_date": trade_date,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
        "plan_id": None,
    }


# ==================== 1. 触发时机 ====================


def test_triggers_on_exact_horizon() -> None:
    """买入日期 + N 天当天触发"""
    with temp_db("due.db") as db:
        engine = make_engine(db, [lot(1, "2026-01-19")])  # 昨天 → T+1
        pending = engine.pending_reviews(NOW)
        assert [(item[0]["id"], item[1]) for item in pending] == [(1, 1)]


def test_all_horizons_can_trigger() -> None:
    with temp_db("horizons.db") as db:
        lots = [
            lot(1, "2026-01-19"),  # → T+1
            lot(2, "2026-01-13"),  # 7 天前 → T+7
            lot(3, "2025-12-21"),  # 30 天前 → T+30
        ]
        engine = make_engine(db, lots)
        pending = engine.pending_reviews(NOW)
        assert sorted((item[0]["id"], item[1]) for item in pending) == [
            (1, 1),
            (2, 7),
            (3, 30),
        ]
        assert set(FOLLOWUP_HORIZONS) == {1, 7, 30}


def test_backfilled_historical_lot_does_not_fire() -> None:
    """核心保护：补录三个月前的买入，不该一次性补出三条复盘"""
    with temp_db("backfill.db") as db:
        engine = make_engine(db, [lot(1, "2025-10-20")])  # 92 天前
        assert engine.pending_reviews(NOW) == []


def test_catchup_window() -> None:
    """追补窗口内仍会触发（停机一两天后重启不会漏），超出则不再补"""
    with temp_db("catchup.db") as db:
        within = make_engine(db, [lot(1, "2026-01-19")])  # T+1 当天
        assert within.pending_reviews(NOW)

        # T+1 已经过去 2 天（= 窗口上限）
        late_ok = make_engine(db, [lot(2, "2026-01-17")])
        assert [item[1] for item in late_ok.pending_reviews(NOW)] == [1]

        # T+1 已过去 3 天 → 超出窗口，不再补
        too_late = make_engine(db, [lot(3, "2026-01-16")])
        assert too_late.pending_reviews(NOW) == []
        assert FOLLOWUP_CATCHUP_DAYS == 2


def test_only_nearby_horizon_fires_for_old_lot() -> None:
    """一笔 7 天前的买入，只触发 T+7，不会同时触发 T+1"""
    with temp_db("single.db") as db:
        engine = make_engine(db, [lot(1, "2026-01-13")])
        assert [item[1] for item in engine.pending_reviews(NOW)] == [7]


def test_unparsable_trade_date_is_skipped() -> None:
    with temp_db("baddate.db") as db:
        engine = make_engine(db, [lot(1, "not-a-date")])
        assert engine.pending_reviews(NOW) == []


# ==================== 2. 不重复 ====================


def test_has_review_prevents_duplicate() -> None:
    with temp_db("dup.db") as db:
        mapper = AdviceMapper(db_file=db)
        engine = make_engine(db, [lot(1, "2026-01-19")])
        assert len(engine.pending_reviews(NOW)) == 1

        mapper.insert_advice(
            {
                "kind": "review",
                "action": "HOLD",
                "symbol": "gds_AUTD",
                "subject_lot_id": 1,
                "review_horizon": 1,
            }
        )
        assert engine.pending_reviews(NOW) == [], "已复盘的买入不该再出现"


def test_suppressed_review_still_pending() -> None:
    """被闸门拦下的复盘意味着用户没收到，必须能重试"""
    with temp_db("suppressed.db") as db:
        mapper = AdviceMapper(db_file=db)
        mapper.insert_advice(
            {
                "kind": "review",
                "action": "HOLD",
                "symbol": "gds_AUTD",
                "subject_lot_id": 1,
                "review_horizon": 1,
                "status": AdviceStatus.SUPPRESSED.value,
                "suppressed_reason": "low_priority",
            }
        )
        engine = make_engine(db, [lot(1, "2026-01-19")])
        assert len(engine.pending_reviews(NOW)) == 1, "suppressed 不应算已复盘"


def test_has_review_is_per_horizon() -> None:
    with temp_db("perhorizon.db") as db:
        mapper = AdviceMapper(db_file=db)
        mapper.insert_advice(
            {
                "kind": "review",
                "action": "HOLD",
                "symbol": "gds_AUTD",
                "subject_lot_id": 1,
                "review_horizon": 1,
            }
        )
        assert mapper.has_review(1, 1) is True
        assert mapper.has_review(1, 7) is False
        assert mapper.has_review(2, 1) is False, "不同买入互不影响"


# ==================== 3. 生成与动作一致 ====================


def indicators(price: float = 900.0, **overrides) -> MarketIndicators:
    base = {
        "current_price": price,
        "avg_24h": price,
        "max_24h": price * 1.01,
        "min_24h": price * 0.99,
        "std_24h": price * 0.002,
        "count_24h": 100,
        "volatility_pct": 0.2,
        "trend_6h_direction": "stable",
        "trend_24h_direction": "stable",
    }
    base.update(overrides)
    return MarketIndicators(**base)


def make_context(price=900.0, lots=None, subject_lot=None, horizon=None) -> AdviceContext:
    lots = list(lots or [])
    return AdviceContext(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        indicators=indicators(price),
        position=compute_position("gds_AUTD", lots, latest_price=price),
        plans=build_plan_states([], summarize_plans([], []), [], TODAY),
        prefs=AdvicePrefs(),
        subject_lot=subject_lot,
        review_horizon=horizon,
    )


def test_review_kind_is_selected() -> None:
    plain = make_context(lots=[lot(1, "2026-01-01")])
    assert select_kind(plain) is AdviceKind.POST_PURCHASE

    reviewing = make_context(
        lots=[lot(1, "2026-01-01")], subject_lot=lot(1, "2026-01-13"), horizon=7
    )
    assert select_kind(reviewing) is AdviceKind.REVIEW


def test_review_action_matches_regular_advice() -> None:
    """复盘不另起一套判断：动作必须与常规建议一致"""
    subject = lot(1, "2026-01-13", grams=10.0, price=900.0)
    ctx = make_context(price=855.0, lots=[subject], subject_lot=subject, horizon=7)
    found = signal_rules.evaluate(ctx)

    regular = build_regular(ctx, found)
    review = build_advice(ctx, found)

    assert review.kind is AdviceKind.REVIEW
    assert review.action is regular.action
    assert review.target_grams == regular.target_grams


def test_review_rationale_mentions_the_lot() -> None:
    subject = lot(1, "2026-01-13", grams=10.0, price=900.0)
    ctx = make_context(price=855.0, lots=[subject], subject_lot=subject, horizon=7)
    draft = build_advice(ctx, signal_rules.evaluate(ctx))

    assert "回访你在 2026-01-13 买入的 10g" in draft.rationale
    assert "T+7" in draft.rationale
    assert "-5.00%" in draft.rationale, "应给出这一笔自己的浮动盈亏"
    assert "成本价" in draft.rationale, "常规理由部分应被保留"


def test_lot_pnl_is_about_this_lot_not_the_position() -> None:
    """整体持仓成本与这一笔的成交价不同，复盘说的是这一笔"""
    old = lot(1, "2025-12-01", grams=10.0, price=800.0)
    subject = lot(2, "2026-01-13", grams=10.0, price=950.0)
    ctx = make_context(
        price=900.0, lots=[old, subject], subject_lot=subject, horizon=7
    )
    # 这一笔：950 → 900 = -5.26%
    assert ctx.lot_pnl_pct() == round((900.0 - 950.0) / 950.0 * 100, 2)
    # 整体成本：(8000 + 9500) / 20 = 875 → +2.86%
    assert ctx.position.avg_cost == 875.0
    assert ctx.position.unrealized_pnl_pct > 0


def test_evidence_contains_review_block() -> None:
    subject = lot(1, "2026-01-13", grams=10.0, price=900.0)
    ctx = make_context(price=855.0, lots=[subject], subject_lot=subject, horizon=7)
    evidence = ctx.to_evidence()
    assert evidence["review"] is not None
    assert evidence["review"]["subject_lot_id"] == 1
    assert evidence["review"]["horizon_days"] == 7
    assert evidence["review"]["lot_pnl_pct"] == -5.0

    assert make_context().to_evidence()["review"] is None


def test_generate_review_persists_and_links_lot() -> None:
    with temp_db("gen.db") as db:
        subject = lot(1, "2026-01-13", grams=10.0, price=900.0)
        engine = make_engine(db, [subject])
        engine.settings = FakeSettings()
        record = engine.generate_review(subject, 7, 855.0, persist=True, use_llm=False)

        assert record.id > 0
        assert record.kind is AdviceKind.REVIEW
        assert record.subject_lot_id == 1
        assert record.review_horizon == 7
        assert record.price_at_advice == 855.0
        assert "T+7" in record.rationale

        stored = engine.advice_mapper.get_advice(record.id)
        assert stored["subject_lot_id"] == 1
        assert stored["review_horizon"] == 7
        assert engine.advice_mapper.has_review(1, 7) is True
        assert engine.pending_reviews(NOW) == []


def test_generate_review_without_persist() -> None:
    with temp_db("preview.db") as db:
        subject = lot(1, "2026-01-13")
        engine = make_engine(db, [subject])
        record = engine.generate_review(subject, 7, 900.0, persist=False, use_llm=False)
        assert record.id == 0
        assert engine.advice_mapper.has_review(1, 7) is False


def test_list_reviews_for_lot() -> None:
    with temp_db("bylot.db") as db:
        mapper = AdviceMapper(db_file=db)
        for horizon in (1, 7):
            mapper.insert_advice(
                {
                    "kind": "review",
                    "action": "HOLD",
                    "symbol": "gds_AUTD",
                    "subject_lot_id": 5,
                    "review_horizon": horizon,
                }
            )
        mapper.insert_advice(
            {
                "kind": "review",
                "action": "HOLD",
                "symbol": "gds_AUTD",
                "subject_lot_id": 6,
                "review_horizon": 1,
            }
        )
        reviews = mapper.list_reviews_for_lot(5)
        assert [item["review_horizon"] for item in reviews] == [1, 7]


# ==================== 4. 老库迁移 ====================


def test_migration_adds_columns_to_existing_db() -> None:
    """老库没有 subject_lot_id / review_horizon，初始化时应自动补列"""
    with temp_db("legacy.db") as db:
        # 造一个「旧版」表结构
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE advice_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
            "kind TEXT NOT NULL, action TEXT NOT NULL, symbol TEXT NOT NULL, "
            "rationale TEXT NOT NULL DEFAULT '', signals TEXT NOT NULL DEFAULT '[]', "
            "evidence TEXT NOT NULL DEFAULT '{}', model_info TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'delivered', "
            "suppressed_reason TEXT NOT NULL DEFAULT '')"
        )
        conn.commit()
        conn.close()

        mapper = AdviceMapper(db_file=db)  # init_tables 应完成迁移
        columns = {
            row[1]
            for row in sqlite3.connect(db).execute("PRAGMA table_info(advice_records)")
        }
        assert {"subject_lot_id", "review_horizon"} <= columns

        advice_id = mapper.insert_advice(
            {
                "kind": "review",
                "action": "HOLD",
                "symbol": "gds_AUTD",
                "subject_lot_id": 9,
                "review_horizon": 30,
            }
        )
        assert mapper.has_review(9, 30) is True
        assert mapper.get_advice(advice_id)["subject_lot_id"] == 9

        # 迁移应可重复执行
        AdviceMapper(db_file=db)
        assert mapper.has_review(9, 30) is True


# ==================== 5. 监控循环接线 ====================


class FakeFollowupEngine:
    def __init__(self, pending=(), action=AdviceAction.HOLD):
        self._pending = list(pending)
        self.action = action
        self.computed: list[tuple] = []
        self.saved: list[dict] = []
        self._next_id = 100

    def pending_reviews(self, at=None):
        return list(self._pending)

    def compute(self, symbol, price, london_cny=None, london_usd=None, **kwargs):
        self.computed.append((symbol, price, kwargs))
        draft = AdviceDraft(
            kind=AdviceKind.REVIEW,
            action=self.action,
            symbol=symbol,
            rationale="复盘理由",
            evidence={"review": {"subject_lot_id": kwargs.get("subject_lot", {}).get("id")}},
        )
        return ComputedAdvice(
            draft=draft,
            rationale="复盘理由",
            model_info="",
            price=price,
            subject_lot_id=kwargs.get("subject_lot", {}).get("id"),
            review_horizon=kwargs.get("review_horizon"),
        )

    def save(self, computed, **kwargs):
        self.saved.append({"id": computed.subject_lot_id, "horizon": computed.review_horizon})
        self._next_id += 1
        return AdviceRecord(
            id=self._next_id,
            created_at="2026-01-20 10:00:00",
            kind=computed.draft.kind,
            action=computed.draft.action,
            symbol=computed.draft.symbol,
            rationale=computed.rationale,
            evidence=computed.draft.evidence,
        )


class FakeNotifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_advice(self, record, current_price, extra_info=None, **kwargs):
        self.sent.append(record)
        return self.ok


class FakePriceMapperForFollowup:
    def __init__(self, latest=900.0):
        self.latest = latest

    def get_latest_price(self, symbol):
        return self.latest


def make_monitor(engine, notifier=None, latest=900.0) -> MonitorService:
    monitor = object.__new__(MonitorService)
    monitor.logger = _test_logger
    monitor.main_symbol = "gds_AUTD"
    monitor.monitor_symbols = ["gds_AUTD"]
    monitor.alert_count = 0
    monitor._last_suppressed = None
    monitor.send_gate = SendGate()
    monitor.advice_engine = engine
    monitor.notification_service = notifier or FakeNotifier()
    monitor.price_mapper = FakePriceMapperForFollowup(latest)
    monitor._followup_timer = DueTimer("买入复盘", FOLLOWUP_REVIEW_SECONDS)
    from service.triggers import FollowupTrigger

    monitor.followup_trigger = FollowupTrigger(
        engine, monitor.price_mapper, FOLLOWUP_REVIEW_SECONDS
    )
    return monitor


def normal_decision() -> GateDecision:
    return GateDecision(
        policy=SendPolicy.NORMAL,
        sge=Session.OPEN,
        intl=Session.OPEN,
        allowed=True,
        reason="",
        detail="正常",
    )


def silent_decision() -> GateDecision:
    return GateDecision(
        policy=SendPolicy.SILENT,
        sge=Session.WEEKEND,
        intl=Session.WEEKEND,
        allowed=False,
        reason="silent",
        detail="周末休市",
    )


def test_monitor_generates_and_delivers_followup() -> None:
    subject = lot(1, "2026-01-19")
    engine = FakeFollowupEngine([(subject, 1)])
    notifier = FakeNotifier()
    monitor = make_monitor(engine, notifier)

    with frozen(NOW):
        monitor._run_followups({}, normal_decision())

    assert len(engine.computed) == 1
    assert engine.computed[0][2]["subject_lot"]["id"] == 1
    assert engine.computed[0][2]["review_horizon"] == 1
    assert len(engine.saved) == 1
    assert len(notifier.sent) == 1
    assert monitor.alert_count == 1


def test_monitor_skips_followup_while_silent() -> None:
    subject = lot(1, "2026-01-19")
    engine = FakeFollowupEngine([(subject, 1)])
    monitor = make_monitor(engine)

    with frozen(NOW):
        monitor._run_followups({}, silent_decision())

    assert engine.computed == [], "休市静默时不应生成复盘（价格是冻结的）"
    assert engine.saved == []


def test_monitor_caps_followups_per_tick() -> None:
    pending = [(lot(i, "2026-01-19"), 1) for i in range(1, 8)]
    engine = FakeFollowupEngine(pending)
    monitor = make_monitor(engine)

    with frozen(NOW):
        monitor._run_followups({}, normal_decision())

    assert len(engine.saved) == 3, "单次最多处理 3 条，避免集中补发"


def test_monitor_throttles_followup_checks() -> None:
    subject = lot(1, "2026-01-19")
    engine = FakeFollowupEngine([(subject, 1)])
    monitor = make_monitor(engine)

    with frozen(NOW):
        monitor._run_followups({}, normal_decision())
        monitor._run_followups({}, normal_decision())  # 同一时刻，未到间隔
    assert len(engine.saved) == 1

    with frozen(NOW + datetime.timedelta(seconds=FOLLOWUP_REVIEW_SECONDS)):
        monitor._run_followups({}, normal_decision())
    assert len(engine.saved) == 2


def test_monitor_skips_followup_without_price() -> None:
    subject = lot(1, "2026-01-19", symbol="hf_XAU")
    engine = FakeFollowupEngine([(subject, 1)])
    monitor = make_monitor(engine, latest=None)

    with frozen(NOW):
        monitor._run_followups({}, normal_decision())

    assert engine.computed == [], "没有价格就不该硬生成"
    assert engine.saved == []


def test_monitor_uses_live_price_from_tick_data() -> None:
    subject = lot(1, "2026-01-19")
    engine = FakeFollowupEngine([(subject, 1)])
    monitor = make_monitor(engine, latest=111.0)  # 库中价（不该被用）

    with frozen(NOW):
        monitor._run_followups({"gds_AUTD": {"price": 888.0}}, normal_decision())

    assert engine.computed[0][1] == 888.0, "应优先用本轮抓到的实时价"


def test_followup_suppressed_by_priority_is_not_persisted() -> None:
    """低优先级 + LOW_FREQ → 不落库，这样下次巡检还能重试"""
    subject = lot(1, "2026-01-19")
    engine = FakeFollowupEngine([(subject, 1)], action=AdviceAction.HOLD)
    monitor = make_monitor(engine)
    low_freq = GateDecision(
        policy=SendPolicy.LOW_FREQ,
        sge=Session.OPEN,
        intl=Session.WEEKEND,
        allowed=True,
        reason="",
        detail="国际金休市",
    )

    with frozen(NOW):
        monitor._run_followups({}, low_freq)

    assert engine.computed, "仍然算了（要拿到 action 才知道优先级）"
    assert engine.saved == [], "被拦下的复盘不该落库，否则 has_review 会把它永久吃掉"


def test_followup_failure_is_isolated() -> None:
    class BrokenEngine(FakeFollowupEngine):
        def pending_reviews(self, at=None):
            raise RuntimeError("db boom")

    monitor = make_monitor(BrokenEngine())
    with frozen(NOW):
        monitor._run_followups({}, normal_decision())  # 不应抛出


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
