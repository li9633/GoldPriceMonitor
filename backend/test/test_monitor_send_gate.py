"""`MonitorService` 建议流程测试。

取代了原来针对 `_handle_alerts` / `_periodic_ai_check` 的测试：现在监控循环做的是
「评估建议 → 判断值不值得推 → 落库并投递」，用假件替换引擎与通知，验证四件事：

1. 休市静默时**不评估、不调用 AI、不发送**；
2. 正常时段生成并投递，且建议被落库；
3. 推送节流：动作没变且价格没明显变动 → 落库为 `suppressed` 且不推送；
4. 两道闸门（时段 / 优先级 + 冷却）都生效。

运行
----
    cd backend
    python -m test.test_monitor_send_gate
"""

import contextlib
import datetime
import logging

import service.monitor_service as monitor_module
from models.advice import (
    AdviceAction,
    AdviceDraft,
    AdviceKind,
    AdviceRecord,
    AdviceStatus,
)
from service.advice.advice_engine import ComputedAdvice
from service.monitor_service import (
    LOG_CLEANUP_SECONDS,
    REVIEW_REFRESH_SECONDS,
    SETTINGS_REFRESH_SECONDS,
    MonitorService,
)
from service.send_gate import SendGate
from utils.due_timer import DueTimer
from utils.market_session import SendPolicy, Session
from test.test_market_session import frozen as _frozen_sessions

_test_logger = logging.getLogger("test.monitor")
_test_logger.addHandler(logging.NullHandler())
_test_logger.propagate = False

WED = datetime.datetime(2025, 9, 24, 10, 0)  # 周三日盘：正常时段
SAT = datetime.datetime(2025, 9, 27, 10, 0)  # 周六：双双休市
HOLIDAY = datetime.datetime(2025, 10, 1, 10, 0)  # 国庆：SGE 休市、国际金正常


@contextlib.contextmanager
def frozen_monitor(at: datetime.datetime):
    """同时冻结 `MonitorService` 自己的 `now` 绑定（节流要用）"""
    with _frozen_sessions(at):
        saved = monitor_module.now
        monitor_module.now = lambda: at
        try:
            yield
        finally:
            monitor_module.now = saved


# ==================== 假件 ====================


def make_draft(action: AdviceAction, grams: float | None = 10.0) -> AdviceDraft:
    return AdviceDraft(
        kind=AdviceKind.POST_PURCHASE,
        action=action,
        symbol="gds_AUTD",
        target_grams=grams,
        rationale="规则生成的理由",
        evidence={"position": {"total_grams": 30.0, "avg_cost": 900.0}},
    )


class FakeAdviceEngine:
    def __init__(self, draft=None, last=None, threshold=0.5):
        self.draft = draft or make_draft(AdviceAction.HOLD)
        self._last = last
        self.threshold = threshold
        self.compute_calls = 0
        self.saved: list[tuple[str, str]] = []
        self._next_id = 0

    def compute(self, symbol, price, london_cny=None, london_usd=None, use_llm=None):
        self.compute_calls += 1
        return ComputedAdvice(
            draft=self.draft, rationale="规则生成的理由", model_info="", price=price
        )

    def save(self, computed, *, status=AdviceStatus.DELIVERED.value, suppressed_reason=""):
        self.saved.append((status, suppressed_reason))
        self._next_id += 1
        return AdviceRecord(
            id=self._next_id,
            created_at="2025-09-24 10:00:00",
            kind=computed.draft.kind,
            action=computed.draft.action,
            symbol=computed.draft.symbol,
            target_grams=computed.draft.target_grams,
            rationale=computed.rationale,
            evidence=computed.draft.evidence,
            status=AdviceStatus(status),
        )

    def last_pushed(self, symbol):
        return self._last

    def price_move_trigger_pct(self):
        return self.threshold


class FakeNotificationService:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent: list[dict] = []

    def send_advice(self, record, current_price, extra_info=None, **kwargs):
        self.sent.append(
            {"record": record, "price": current_price, "extra_info": extra_info}
        )
        return self.ok


def make_monitor(engine=None, notifier=None, interval_minutes=5) -> MonitorService:
    monitor = object.__new__(MonitorService)
    monitor.logger = _test_logger
    monitor.main_symbol = "gds_AUTD"
    monitor.monitor_symbols = ["gds_AUTD"]
    monitor.ai_check_interval_minutes = interval_minutes
    monitor.check_count = 0
    monitor.alert_count = 0
    monitor._last_suppressed = None
    monitor.send_gate = SendGate()
    monitor.advice_engine = engine or FakeAdviceEngine()
    monitor.notification_service = notifier or FakeNotificationService()
    # 定时器与 __init__ 里保持一致
    monitor._advice_timer = DueTimer("建议评估", interval_minutes * 60)
    monitor._review_timer = DueTimer("回访价格回填", REVIEW_REFRESH_SECONDS)
    monitor._settings_timer = DueTimer("设置刷新", SETTINGS_REFRESH_SECONDS)
    monitor._cleanup_timer = DueTimer("日志清理", LOG_CLEANUP_SECONDS)
    return monitor


# ==================== 1. 休市静默 ====================


def test_silent_skips_everything() -> None:
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(SAT):
        decision = monitor.send_gate.policy_decision()
        monitor._advise({}, 900.0, decision)

    assert decision.policy is SendPolicy.SILENT
    assert engine.compute_calls == 0, "静默时不应评估建议（省 AI 调用）"
    assert engine.saved == [], "静默时不应落库"
    assert notifier.sent == []


# ==================== 2. 正常时段 ====================


def test_normal_generates_and_delivers() -> None:
    engine = FakeAdviceEngine(make_draft(AdviceAction.BUY_PARTIAL, grams=25.0))
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        decision = monitor.send_gate.policy_decision()
        monitor._advise({}, 900.0, decision)

    assert engine.compute_calls == 1
    assert engine.saved == [(AdviceStatus.DELIVERED.value, "")]
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["price"] == 900.0
    assert monitor.alert_count == 1


def test_intl_only_still_delivers() -> None:
    """国庆：SGE 休市但国际金正常 → 照常生成并推送"""
    engine = FakeAdviceEngine(make_draft(AdviceAction.WAIT, grams=None))
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(HOLIDAY):
        decision = monitor.send_gate.policy_decision()
        monitor._advise({}, 900.0, decision)

    assert decision.policy is SendPolicy.INTL_ONLY
    assert len(notifier.sent) == 1


def test_delivery_failure_does_not_count() -> None:
    engine = FakeAdviceEngine()
    notifier = FakeNotificationService(ok=False)
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        monitor._advise({}, 900.0, monitor.send_gate.policy_decision())

    assert len(notifier.sent) == 1, "仍然尝试投递了"
    assert monitor.alert_count == 0, "投递失败不应计入推送次数"
    assert engine.saved == [(AdviceStatus.DELIVERED.value, "")], "建议仍然落库"


# ==================== 3. 节流 ====================


def test_interval_throttle_skips_recompute() -> None:
    engine = FakeAdviceEngine()
    monitor = make_monitor(engine, interval_minutes=5)

    with frozen_monitor(WED):
        decision = monitor.send_gate.policy_decision()
        monitor._advise({}, 900.0, decision)
        monitor._advise({}, 900.0, decision)  # 同一时刻，未到巡检间隔
        monitor._advise({}, 900.0, decision)

    assert engine.compute_calls == 1, "巡检间隔内不应重复评估"


def test_recompute_after_interval() -> None:
    engine = FakeAdviceEngine()
    monitor = make_monitor(engine, interval_minutes=5)

    with frozen_monitor(WED):
        monitor._advise({}, 900.0, monitor.send_gate.policy_decision())
    later = WED + datetime.timedelta(minutes=6)
    with frozen_monitor(later):
        monitor._advise({}, 900.0, monitor.send_gate.policy_decision())

    assert engine.compute_calls == 2


def test_duplicate_action_is_suppressed() -> None:
    """动作没变且价格没明显变动 → 落库为 suppressed，且不推送"""
    draft = make_draft(AdviceAction.HOLD, grams=None)
    last = AdviceRecord(
        id=1,
        created_at="2025-09-24 09:00:00",
        kind=AdviceKind.POST_PURCHASE,
        action=AdviceAction.HOLD,
        symbol="gds_AUTD",
        price_at_advice=900.0,
    )
    engine = FakeAdviceEngine(draft, last=last, threshold=0.5)
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        monitor._advise({}, 900.5, monitor.send_gate.policy_decision())

    assert notifier.sent == [], "同类建议不应重复推送"
    assert engine.saved == [(AdviceStatus.SUPPRESSED.value, "duplicate")]
    assert monitor.alert_count == 0


def test_action_change_is_pushed() -> None:
    draft = make_draft(AdviceAction.ADD, grams=15.0)
    last = AdviceRecord(
        id=1,
        created_at="2025-09-24 09:00:00",
        kind=AdviceKind.POST_PURCHASE,
        action=AdviceAction.HOLD,  # 动作变了
        symbol="gds_AUTD",
        price_at_advice=900.0,
    )
    engine = FakeAdviceEngine(draft, last=last)
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        monitor._advise({}, 900.2, monitor.send_gate.policy_decision())

    assert len(notifier.sent) == 1
    assert engine.saved == [(AdviceStatus.DELIVERED.value, "")]


def test_price_move_triggers_push() -> None:
    draft = make_draft(AdviceAction.HOLD, grams=None)
    last = AdviceRecord(
        id=1,
        created_at="2025-09-24 09:00:00",
        kind=AdviceKind.POST_PURCHASE,
        action=AdviceAction.HOLD,
        symbol="gds_AUTD",
        price_at_advice=900.0,
    )
    engine = FakeAdviceEngine(draft, last=last, threshold=0.5)
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        # 900 → 906 涨 0.67% ≥ 0.5% → 放行
        monitor._advise({}, 906.0, monitor.send_gate.policy_decision())

    assert len(notifier.sent) == 1


def test_first_advice_always_pushes() -> None:
    engine = FakeAdviceEngine(last=None)
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        monitor._advise({}, 900.0, monitor.send_gate.policy_decision())

    assert len(notifier.sent) == 1


# ==================== 4. 优先级闸门 ====================


def test_low_freq_suppresses_low_urgency() -> None:
    """国际金休市、SGE 开市时只放行高优先级；HOLD 属于低优先级"""
    engine = FakeAdviceEngine(make_draft(AdviceAction.HOLD, grams=None))
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    # 构造 LOW_FREQ 决策（该组合在当前规则下不可达，直接用构造的方式验证闸门）
    low_freq = _low_freq_decision()
    with frozen_monitor(WED):
        monitor._advise({}, 900.0, low_freq)

    assert notifier.sent == []
    assert engine.saved == [(AdviceStatus.SUPPRESSED.value, "low_priority")]


def test_low_freq_allows_high_urgency() -> None:
    engine = FakeAdviceEngine(make_draft(AdviceAction.STOP_LOSS, grams=15.0))
    notifier = FakeNotificationService()
    monitor = make_monitor(engine, notifier)

    with frozen_monitor(WED):
        monitor._advise({}, 900.0, _low_freq_decision())

    assert len(notifier.sent) == 1, "止损属高优先级，应当放行"


def _low_freq_decision():
    """构造一个 LOW_FREQ 决策。

    正常规则下这个组合不可达（国际金休市时 SGE 也休市），所以直接构造来验证闸门本身。
    """
    from service.send_gate import GateDecision

    return GateDecision(
        policy=SendPolicy.LOW_FREQ,
        sge=Session.OPEN,
        intl=Session.WEEKEND,
        allowed=True,
        reason="",
        detail="国际金休市",
    )


# ==================== 5. 辅助信息 ====================


def test_build_extra_info_includes_london_and_model() -> None:
    monitor = make_monitor()
    extra = monitor._build_extra_info(
        {"hf_XAU": {"price": 2300.0, "converted_cny_price": 531.2}}, "p/m"
    )
    assert extra["london_gold_usd"] == 2300.0
    assert extra["london_gold_cny"] == 531.2
    assert extra["ai_model_info"] == "p/m"

    assert monitor._build_extra_info({}, "") == {}


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
