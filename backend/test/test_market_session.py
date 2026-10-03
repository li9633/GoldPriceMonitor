"""市场时段与发送闸门的单元测试。

覆盖 `docs/send-policy-plan.md` 里记录的三个边界问题，以及两道闸门的判定：

1. **调休**：`chinese_calendar.is_workday()` 对调休上班的周末返回 `True`，但交易所
   周末从不开市 —— 必须用 `is_holiday()`。
2. **夜盘跨日**：`00:00-02:30` 属于**前一个交易日**的夜间盘。周六凌晨仍应算开市，
   周一凌晨则应算休市（周日晚没有夜盘）。
3. **国际金口径**：北京时间周六早晨收盘、周一早晨开盘，按星期 + 宽松边界判断。

运行
----
    cd backend
    python -m test.test_market_session

也可以直接被 pytest 收集。
"""

import contextlib
import datetime

from service import send_gate as send_gate_module
from service.send_gate import (
    SendDeduplicator,
    SendGate,
)
from utils import market_session
from utils.market_session import (
    SendPolicy,
    Session,
    intl_session,
    policy_for,
    send_policy,
    sge_session,
)

DEFAULT_WINDOWS = [
    ("09:00", "11:30"),
    ("13:30", "15:30"),
    ("20:00", "23:59"),
    ("00:00", "02:30"),
]


@contextlib.contextmanager
def frozen(at: datetime.datetime, windows=None):
    """冻结时间与交易时段配置，避免测试依赖数据库与当前时间。

    `market_session` 与 `send_gate` 各自持有 `now` 的模块级引用，所以两处都要替换。
    """
    saved_now = market_session.now
    saved_read = market_session._read_trading_hours
    saved_gate_now = send_gate_module.now
    market_session.now = lambda: at
    market_session._read_trading_hours = lambda: list(windows or DEFAULT_WINDOWS)
    send_gate_module.now = lambda: at
    market_session.invalidate_cache()
    try:
        yield
    finally:
        market_session.now = saved_now
        market_session._read_trading_hours = saved_read
        send_gate_module.now = saved_gate_now
        market_session.invalidate_cache()


# ==================== 日历前置条件 ====================


def test_calendar_assumptions_hold() -> None:
    """测试依赖的日期性质先自查一遍，日历数据变化时能立刻发现"""
    from chinese_calendar import is_holiday, is_workday

    # 调休上班的周末：is_workday 为 True，但交易所休市
    assert is_workday(datetime.date(2025, 9, 28)) is True
    assert is_holiday(datetime.date(2025, 9, 28)) is False
    assert market_session.is_trading_day(datetime.date(2025, 9, 28)) is False

    assert is_workday(datetime.date(2025, 10, 11)) is True
    assert market_session.is_trading_day(datetime.date(2025, 10, 11)) is False

    # 国庆：节假日
    assert market_session.is_trading_day(datetime.date(2025, 10, 1)) is False
    # 普通周三：交易日
    assert market_session.is_trading_day(datetime.date(2025, 9, 24)) is True
    # 普通周六：非交易日
    assert market_session.is_trading_day(datetime.date(2025, 9, 27)) is False


# ==================== SGE 时段 ====================


def test_sge_session_normal_hours() -> None:
    cases = [
        (datetime.datetime(2025, 9, 24, 10, 0), Session.OPEN, "周三日盘"),
        (datetime.datetime(2025, 9, 24, 12, 0), Session.CLOSED, "周三午休"),
        (datetime.datetime(2025, 9, 24, 21, 0), Session.OPEN, "周三夜盘"),
        (datetime.datetime(2025, 9, 25, 1, 0), Session.OPEN, "周四凌晨（周三夜盘延续）"),
    ]
    for at, expected, label in cases:
        with frozen(at):
            assert sge_session() is expected, f"{label} 期望 {expected}"


def test_sge_session_night_session_ownership() -> None:
    """夜盘 00:00-02:30 归属前一个交易日 —— 这是修复的第二个问题"""
    # 周六凌晨：前一日（周五）是交易日，周五夜盘延续到周六 02:30 → 开市
    with frozen(datetime.datetime(2025, 9, 27, 1, 0)):
        assert sge_session() is Session.OPEN, "周五夜盘延续到周六 02:30，应为开市"

    # 周六凌晨 02:31：夜盘已结束
    with frozen(datetime.datetime(2025, 9, 27, 2, 31)):
        assert sge_session() is Session.WEEKEND

    # 周一凌晨：前一日（周日）不是交易日，周日晚没有夜盘 → 休市
    with frozen(datetime.datetime(2025, 9, 29, 1, 0)):
        assert sge_session() is Session.CLOSED, "周日晚无夜盘，周一凌晨应休市"


def test_sge_session_holiday_and_makeup_workday() -> None:
    """调休上班的周末仍然是休市 —— 这是修复的第一个问题"""
    with frozen(datetime.datetime(2025, 9, 28, 10, 0)):
        assert sge_session() is Session.WEEKEND, "调休周日不得判为交易时段"

    with frozen(datetime.datetime(2025, 10, 11, 10, 0)):
        assert sge_session() is Session.WEEKEND, "调休周六不得判为交易时段"

    with frozen(datetime.datetime(2025, 10, 1, 10, 0)):
        assert sge_session() is Session.HOLIDAY, "国庆应判为法定节假日"


def test_sge_session_accepts_merged_cross_midnight_window() -> None:
    """也支持把夜盘写成一个跨午夜窗口：20:00-02:30"""
    merged = [("09:00", "11:30"), ("13:30", "15:30"), ("20:00", "02:30")]
    with frozen(datetime.datetime(2025, 9, 27, 1, 0), windows=merged):
        assert sge_session() is Session.OPEN
    with frozen(datetime.datetime(2025, 9, 29, 1, 0), windows=merged):
        assert sge_session() is Session.CLOSED


# ==================== 国际金时段 ====================


def test_intl_session() -> None:
    cases = [
        (datetime.datetime(2025, 9, 24, 12, 0), Session.OPEN, "周三"),
        (datetime.datetime(2025, 9, 26, 23, 0), Session.OPEN, "周五晚间"),
        (datetime.datetime(2025, 9, 27, 1, 0), Session.OPEN, "周六凌晨（周五盘未收）"),
        (datetime.datetime(2025, 9, 27, 6, 0), Session.WEEKEND, "周六早晨已收盘"),
        (datetime.datetime(2025, 9, 28, 12, 0), Session.WEEKEND, "周日"),
        (datetime.datetime(2025, 9, 29, 1, 0), Session.WEEKEND, "周一开盘前"),
        (datetime.datetime(2025, 9, 29, 8, 0), Session.OPEN, "周一已开盘"),
    ]
    for at, expected, label in cases:
        with frozen(at):
            assert intl_session() is expected, f"{label} 期望 {expected}"


# ==================== 策略矩阵 ====================


def test_send_policy_matrix() -> None:
    cases = [
        (datetime.datetime(2025, 9, 24, 10, 0), SendPolicy.NORMAL, "两个市场都开市"),
        (datetime.datetime(2025, 9, 27, 1, 0), SendPolicy.NORMAL, "周六凌晨两者都开"),
        (datetime.datetime(2025, 9, 27, 10, 0), SendPolicy.SILENT, "周末双双休市"),
        (datetime.datetime(2025, 10, 1, 10, 0), SendPolicy.INTL_ONLY, "国庆休市，国际金正常"),
        (datetime.datetime(2025, 9, 29, 1, 0), SendPolicy.SILENT, "周一凌晨双双休市"),
        (datetime.datetime(2025, 9, 24, 12, 0), SendPolicy.INTL_ONLY, "午休，国际金正常"),
    ]
    for at, expected, label in cases:
        with frozen(at):
            assert send_policy() is expected, f"{label} 期望 {expected}"


def test_policy_for_is_total() -> None:
    """任意状态组合都要能给出策略，不能抛异常"""
    for sge in Session:
        for intl in Session:
            assert isinstance(policy_for(sge, intl), SendPolicy)


# ==================== 发送闸门 ====================


def test_gate_silent_blocks_before_ai() -> None:
    gate = SendGate()
    with frozen(datetime.datetime(2025, 9, 27, 10, 0)):
        decision = gate.policy_decision()
    assert decision.allowed is False
    assert decision.reason == "silent"
    assert "休市" in decision.detail


def test_gate_normal_allows() -> None:
    gate = SendGate()
    with frozen(datetime.datetime(2025, 9, 24, 10, 0)):
        decision = gate.policy_decision()
    assert decision.allowed is True
    assert decision.reason == ""


def test_gate_low_freq_only_high_urgency() -> None:
    gate = SendGate()
    with frozen(datetime.datetime(2025, 9, 24, 10, 0)):
        decision = gate.policy_decision()
    # 手工构造 LOW_FREQ 决策，直接验证优先级过滤
    low_freq = type(decision)(
        policy=SendPolicy.LOW_FREQ,
        sge=Session.OPEN,
        intl=Session.WEEKEND,
        allowed=True,
        reason="",
        detail="",
    )
    at = datetime.datetime(2025, 9, 24, 10, 0)
    assert gate.review(low_freq, key="k1", price=900.0, urgency="medium", at=at).reason == (
        "low_priority"
    )
    assert gate.review(low_freq, key="k2", price=900.0, urgency=None, at=at).allowed is False
    assert gate.review(low_freq, key="k3", price=900.0, urgency="high", at=at).allowed is True


# ==================== 去重 ====================


def test_dedup_suppresses_repeat_within_cooldown() -> None:
    dedup = SendDeduplicator(cooldown_minutes=10, price_change_threshold=0.003)
    at = datetime.datetime(2025, 9, 24, 10, 0)

    assert dedup.check("k", 900.0, at).allowed is True
    repeat = dedup.check("k", 900.0, at + datetime.timedelta(minutes=1))
    assert repeat.allowed is False
    assert repeat.reason == "duplicate"

    # 价格变动超过 0.3% → 放行
    moved = dedup.check("k", 900.0 * 1.005, at + datetime.timedelta(minutes=2))
    assert moved.allowed is True

    # 冷却期结束后 → 放行
    assert dedup.check("k", 900.0, at + datetime.timedelta(minutes=11)).allowed is True

    # 不同键互不影响
    assert dedup.check("other", 900.0, at).allowed is True


def test_dedup_boundary_at_exactly_threshold() -> None:
    dedup = SendDeduplicator(cooldown_minutes=10, price_change_threshold=0.003)
    at = datetime.datetime(2025, 9, 24, 10, 0)
    assert dedup.check("k", 1000.0, at).allowed is True
    # 恰好 0.3%：change < threshold 为假 → 放行
    assert dedup.check("k", 1003.0, at).allowed is True


def test_dedup_table_stays_bounded() -> None:
    """长期运行下去重表不能无限增长"""
    dedup = SendDeduplicator(cooldown_minutes=1)
    base = datetime.datetime(2025, 9, 24, 10, 0)
    for i in range(500):
        at = base + datetime.timedelta(minutes=i)
        dedup.check(f"key-{i}", 900.0, at)
    assert len(dedup._sent) <= 64, f"去重表增长到 {len(dedup._sent)} 条"


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
