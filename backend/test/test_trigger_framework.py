"""触发器框架测试（通知阶段 C）。

验证 infra/notification 方案 §4.2 的分层：

1. `SendDeduplicator` 支持事件声明的冷却参数（默认值不变）；
2. `TriggerRegistry` 依序评估、汇总事件与抑制、单触发器异常不影响其他；
3. `AdviceTrigger`：动作变化产出事件（dedup_key/urgency/价格基准随口径）；
   动作未变且价格未动产出抑制（computed 携带，供落库 suppressed）；
4. `FollowupTrigger`：休市产出「不落库」抑制（computed=None）。

运行
----
    cd backend
    python -m test.test_trigger_framework
"""

import datetime

from models.advice import AdviceAction
from service.send_gate import SendDeduplicator
from service.triggers import (
    AdviceTrigger,
    FollowupTrigger,
    Suppression,
    TickContext,
    TriggerOutcome,
    TriggerRegistry,
)
from test.test_monitor_send_gate import (
    FakeAdviceEngine,
    make_draft,
)
from utils.market_session import SendPolicy, Session

WED = datetime.datetime(2025, 9, 24, 10, 0)


def normal_tick(**overrides) -> TickContext:
    from service.send_gate import GateDecision

    decision = GateDecision(
        policy=SendPolicy.NORMAL,
        sge=Session.OPEN,
        intl=Session.OPEN,
        allowed=True,
        reason="",
        detail="正常",
    )
    defaults = {
        "at": WED,
        "decision": decision,
        "prices_data": {},
        "main_symbol": "gds_AUTD",
        "market_symbol": None,
        "market_price": 900.0,
        "london_cny": 531.2,
        "london_usd": 2300.0,
        "valuation_note": "",
    }
    defaults.update(overrides)
    return TickContext(**defaults)


# ==================== 去重器冷却参数 ====================


def test_dedup_default_cooldown_unchanged() -> None:
    """不传冷却参数：沿用实例默认 10 分钟"""
    dedup = SendDeduplicator()
    base = WED
    assert dedup.check("k", 100.0, base).allowed
    blocked = dedup.check("k", 100.0, base + datetime.timedelta(minutes=5))
    assert not blocked.allowed and blocked.reason == "duplicate"
    after = dedup.check("k", 100.0, base + datetime.timedelta(minutes=11))
    assert after.allowed


def test_dedup_per_call_cooldown_override() -> None:
    """事件声明更长的冷却：同键在自定义冷却期内被拦、过后放行"""
    dedup = SendDeduplicator()
    base = WED
    assert dedup.check("k", 100.0, base, cooldown_minutes=60).allowed
    blocked = dedup.check("k", 100.0, base + datetime.timedelta(minutes=30), cooldown_minutes=60)
    assert not blocked.allowed
    after = dedup.check("k", 100.0, base + datetime.timedelta(minutes=61), cooldown_minutes=60)
    assert after.allowed


# ==================== 注册表 ====================


class ExplodingTrigger:
    """评估时抛异常的触发器 —— 不得影响其他触发器"""

    @property
    def name(self) -> str:
        return "exploding"

    def evaluate(self, tick) -> TriggerOutcome:
        raise RuntimeError("boom")


class StubTrigger:
    def __init__(self, name: str, outcome: TriggerOutcome) -> None:
        self._name = name
        self._outcome = outcome

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, tick) -> TriggerOutcome:
        return self._outcome


def test_registry_collects_and_isolates() -> None:
    ok = TriggerOutcome(
        events=[],
        suppressed=[Suppression(source="s", reason="r", detail="d")],
    )
    registry = TriggerRegistry(
        [StubTrigger("a", ok), ExplodingTrigger(), StubTrigger("b", ok)]
    )
    outcome = registry.evaluate_all(normal_tick())
    assert len(outcome.suppressed) == 2, "爆炸的触发器不应影响其他"


# ==================== AdviceTrigger ====================


def test_advice_trigger_action_change_emits_event() -> None:
    engine = FakeAdviceEngine(make_draft(AdviceAction.BUY_PARTIAL))
    trigger = AdviceTrigger(engine, 60.0)
    outcome = trigger.evaluate(normal_tick(market_price=905.0))

    assert len(outcome.events) == 1
    ev = outcome.events[0]
    assert ev.dedup_key == "gds_AUTD#advice#BUY_PARTIAL"
    assert ev.price_basis == 905.0
    assert ev.current_price == 905.0
    assert ev.computed is not None and ev.save_suppressed is True
    assert ev.extra_info["london_gold_cny"] == 531.2
    assert outcome.suppressed == []


def _hold_last(price: float = 900.0):
    from models.advice import AdviceKind, AdviceRecord

    return AdviceRecord(
        id=1,
        created_at="2025-09-24 09:00:00",
        kind=AdviceKind.POST_PURCHASE,
        action=AdviceAction.HOLD,
        symbol="gds_AUTD",
        price_at_advice=price,
    )


def test_advice_trigger_duplicate_suppressed_with_computed() -> None:
    """动作未变 + 价格未动：产出抑制（computed 携带，供落库 suppressed）"""
    engine = FakeAdviceEngine(make_draft(AdviceAction.HOLD), last=_hold_last(900.0))
    trigger = AdviceTrigger(engine, 60.0)

    outcome = trigger.evaluate(normal_tick(market_price=900.0))
    assert outcome.events == []
    assert len(outcome.suppressed) == 1
    sup = outcome.suppressed[0]
    assert sup.reason == "duplicate"
    assert sup.computed is not None, "建议类抑制要落库"


def test_advice_trigger_respects_interval() -> None:
    engine = FakeAdviceEngine(make_draft(AdviceAction.BUY_PARTIAL))
    trigger = AdviceTrigger(engine, 300.0)
    first = trigger.evaluate(normal_tick())
    assert len(first.events) == 1, "首次评估应执行"
    second = trigger.evaluate(normal_tick(at=WED + datetime.timedelta(seconds=60)))
    assert second.events == [] and second.suppressed == [], "间隔内不再评估"


def test_advice_trigger_uses_market_view_price() -> None:
    """INTL_ONLY 口径：评估价与去重基准均为口径价格"""
    engine = FakeAdviceEngine(make_draft(AdviceAction.BUY_PARTIAL))
    trigger = AdviceTrigger(engine, 60.0)
    tick = normal_tick(
        market_symbol="hf_XAU",
        market_price=540.0,
        valuation_note="可能有偏差",
    )
    outcome = trigger.evaluate(tick)
    ev = outcome.events[0]
    assert ev.price_basis == 540.0
    assert ev.extra_info["valuation_note"] == "可能有偏差"


# ==================== FollowupTrigger ====================


class FakeFollowupEngine:
    def __init__(self, pending):
        self._pending = pending
        self.computed = []
        self.price_mapper = type(
            "M", (), {"get_latest_price": staticmethod(lambda s: 900.0)}
        )()

    def pending_reviews(self, at):
        return self._pending

    def compute(self, symbol, price, *args, **kwargs):
        from service.advice.advice_engine import ComputedAdvice

        self.computed.append((symbol, price, kwargs))
        draft = make_draft(AdviceAction.HOLD)
        return ComputedAdvice(draft=draft, rationale="r", model_info="", price=price)


def silent_tick() -> TickContext:
    from service.send_gate import GateDecision

    decision = GateDecision(
        policy=SendPolicy.SILENT,
        sge=Session.WEEKEND,
        intl=Session.WEEKEND,
        allowed=False,
        reason="silent",
        detail="双休市",
    )
    return normal_tick(decision=decision)


def test_followup_silent_suppression_not_persisted() -> None:
    """休市抑制：computed=None —— 刻意不落库，追补窗口内会重试"""
    trigger = FollowupTrigger(FakeFollowupEngine([]), price_mapper=None)
    outcome = trigger.evaluate(silent_tick())
    assert len(outcome.suppressed) == 1
    assert outcome.suppressed[0].computed is None
    assert outcome.suppressed[0].source == "买入复盘"


def test_followup_pending_lot_emits_event() -> None:
    lot = {"id": 7, "symbol": "gds_AUTD"}
    engine = FakeFollowupEngine([(lot, 1)])
    mapper = type("M", (), {"get_latest_price": staticmethod(lambda s: 900.0)})()
    trigger = FollowupTrigger(engine, price_mapper=mapper)
    outcome = trigger.evaluate(normal_tick())
    assert len(outcome.events) == 1
    ev = outcome.events[0]
    assert ev.dedup_key == "gds_AUTD#review#7#1"
    assert ev.save_suppressed is False, "复盘被闸门拦下时不得落库"
    assert ev.computed is not None


def test_followup_skips_lot_without_price() -> None:
    class NoPriceMapper:
        def get_latest_price(self, symbol):
            return None

    lot = {"id": 7, "symbol": "gds_AUTD"}
    engine = FakeFollowupEngine([(lot, 1)])
    trigger = FollowupTrigger(engine, price_mapper=NoPriceMapper())
    outcome = trigger.evaluate(normal_tick(prices_data={}))
    assert outcome.events == [], "没有可用价格应跳过"


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
