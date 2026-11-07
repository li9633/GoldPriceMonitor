"""交易日历 provider 链测试（infra-refactor-plan §1）。

验证回退链、缓存分层与降级观测：

1. lib 源：覆盖年份内权威，超范围返回 UNKNOWN；
2. weekly 兜底：周末=假日、工作日=交易日，永不 UNKNOWN；
3. 在线源：status 映射、对象/列表两种响应形态、请求失败 → UNKNOWN；
4. 门面链路：lib 优先 → 在线结果落库复用 → weekly 兜底不落库；
5. `market_session.is_trading_day` 经门面后行为与改造前一致。

运行
----
    cd backend
    python -m test.test_calendar_providers
"""

import datetime
import tempfile
from unittest import mock

from mapper.calendar_cache_mapper import CalendarCacheMapper
from providers.calendar.base import CalendarVerdict, TradingCalendarProvider
from providers.calendar.chinese_lib import ChineseCalendarLibProvider
from providers.calendar.manager import TradingCalendar
from providers.calendar.online import OnlineCalendarProvider
from providers.calendar.weekly import WeeklyRuleProvider
from utils import market_session

D_HOLIDAY = datetime.date(2026, 10, 1)  # 国庆（lib 覆盖内）
D_WORKDAY = datetime.date(2026, 6, 1)  # 周一（lib 覆盖内）
D_FUTURE = datetime.date(2027, 6, 1)  # lib 覆盖外
D_SATURDAY = datetime.date(2025, 10, 11)  # 调休上班的周六


# ==================== 假件 ====================


class FakeProvider(TradingCalendarProvider):
    def __init__(self, name: str, verdicts: dict, default=CalendarVerdict.UNKNOWN):
        self._name = name
        self._verdicts = verdicts
        self._default = default
        self.calls: list[datetime.date] = []

    @property
    def name(self) -> str:
        return self._name

    def holiday_info(self, day):
        self.calls.append(day)
        return self._verdicts.get(day, self._default)


def make_manager(
    lib_verdicts=None,
    online_verdicts=None,
    online_default=CalendarVerdict.UNKNOWN,
):
    tmp = tempfile.TemporaryDirectory()
    cache = CalendarCacheMapper(db_file=f"{tmp.name}/calendar.db")
    lib = FakeProvider(
        "chinese-calendar",
        lib_verdicts or {},
        default=CalendarVerdict.UNKNOWN,
    )
    online = FakeProvider(
        "haoshenqi", online_verdicts or {}, default=online_default
    )
    calendar = TradingCalendar(
        providers=[lib, online, WeeklyRuleProvider()], cache=cache
    )
    return calendar, lib, online, tmp


# ==================== 各源单独验证 ====================


def test_lib_provider_authoritative_within_coverage() -> None:
    lib = ChineseCalendarLibProvider()
    assert lib.holiday_info(D_HOLIDAY) is CalendarVerdict.KNOWN_HOLIDAY
    assert lib.holiday_info(D_WORKDAY) is CalendarVerdict.KNOWN_WORKDAY


def test_lib_provider_unknown_beyond_coverage() -> None:
    lib = ChineseCalendarLibProvider()
    assert lib.holiday_info(D_FUTURE) is CalendarVerdict.UNKNOWN


def test_weekly_rule_never_unknown() -> None:
    weekly = WeeklyRuleProvider()
    assert weekly.holiday_info(D_SATURDAY) is CalendarVerdict.KNOWN_HOLIDAY
    assert weekly.holiday_info(D_WORKDAY) is CalendarVerdict.KNOWN_WORKDAY
    assert weekly.holiday_info(D_FUTURE) is not CalendarVerdict.UNKNOWN


def _mock_response(payload):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json = mock.Mock(return_value=payload)
    return resp


def test_online_provider_status_mapping() -> None:
    online = OnlineCalendarProvider()
    cases = {
        3: CalendarVerdict.KNOWN_HOLIDAY,  # 法定假日
        1: CalendarVerdict.KNOWN_HOLIDAY,  # 周末
        0: CalendarVerdict.KNOWN_WORKDAY,  # 工作日
        2: CalendarVerdict.KNOWN_WORKDAY,  # 调休上班
    }
    for status, expected in cases.items():
        with mock.patch(
            "providers.calendar.online.requests.get",
            return_value=_mock_response({"status": status, "date": "2027-06-01"}),
        ):
            assert online.holiday_info(D_FUTURE) is expected, f"status={status}"


def test_online_provider_handles_list_response() -> None:
    """个别日期返回列表形态，取与日期匹配的元素"""
    online = OnlineCalendarProvider()
    payload = [
        {"date": "2027-06-02", "status": 3},
        {"date": "2027-06-01", "status": 0},
    ]
    with mock.patch(
        "providers.calendar.online.requests.get",
        return_value=_mock_response(payload),
    ):
        assert online.holiday_info(D_FUTURE) is CalendarVerdict.KNOWN_WORKDAY


def test_online_provider_unknown_on_failure() -> None:
    online = OnlineCalendarProvider()
    with mock.patch(
        "providers.calendar.online.requests.get", side_effect=RuntimeError("boom")
    ):
        assert online.holiday_info(D_FUTURE) is CalendarVerdict.UNKNOWN


# ==================== 门面链路 ====================


def test_chain_lib_wins_and_online_not_called() -> None:
    calendar, lib, online, tmp = make_manager(
        lib_verdicts={D_HOLIDAY: CalendarVerdict.KNOWN_HOLIDAY}
    )
    try:
        result = calendar.resolve(D_HOLIDAY)
        assert result.source == "chinese-calendar"
        assert online.calls == [], "lib 能答就不应请求在线源"
    finally:
        tmp.cleanup()


def test_chain_online_result_persisted_and_reused() -> None:
    calendar, lib, online, tmp = make_manager(
        online_verdicts={D_FUTURE: CalendarVerdict.KNOWN_HOLIDAY}
    )
    try:
        first = calendar.resolve(D_FUTURE)
        assert first.verdict is CalendarVerdict.KNOWN_HOLIDAY
        assert first.source == "haoshenqi"
        assert online.calls == [D_FUTURE]

        # 第二次解析命中内存缓存，不再请求在线源
        again = calendar.resolve(D_FUTURE)
        assert again.source == "haoshenqi"
        assert online.calls == [D_FUTURE]

        # 新门面实例（内存为空）直接命中落库缓存，仍不请求在线源
        cache_only = TradingCalendar(
            providers=[lib, online, WeeklyRuleProvider()], cache=calendar._cache
        )
        third = cache_only.resolve(D_FUTURE)
        assert third.source == "haoshenqi(cached)"
        assert third.verdict is CalendarVerdict.KNOWN_HOLIDAY
        assert len(online.calls) == 1
    finally:
        tmp.cleanup()


def test_chain_weekly_fallback_not_persisted() -> None:
    """weekly 兜底结果不落库 —— 2027 安排发布后在线源要能接棒"""
    calendar, lib, online, tmp = make_manager()  # lib/online 全 UNKNOWN
    try:
        result = calendar.resolve(D_FUTURE)
        assert result.source == "weekly-rule"
        assert calendar._cache.get(D_FUTURE) is None, "weekly 结果不得进缓存"
        assert online.calls == [D_FUTURE], "在线源应被尝试过一次"
    finally:
        tmp.cleanup()


def test_chain_memory_cache_hits() -> None:
    calendar, lib, online, tmp = make_manager(
        online_verdicts={D_FUTURE: CalendarVerdict.KNOWN_WORKDAY}
    )
    try:
        calendar.resolve(D_FUTURE)
        calls_before = len(lib.calls) + len(online.calls)
        calendar.resolve(D_FUTURE)
        assert len(lib.calls) + len(online.calls) == calls_before, "命中内存缓存"
    finally:
        tmp.cleanup()


def test_status_reports_degradation() -> None:
    calendar, _lib, _online, tmp = make_manager(
        online_verdicts={D_FUTURE: CalendarVerdict.KNOWN_WORKDAY}
    )
    try:
        with mock.patch("providers.calendar.manager.now") as mock_now:
            mock_now.return_value = datetime.datetime(2027, 6, 1, 12, 0, 0)
            status = calendar.status()
        assert status["degraded"] is True
        assert status["active_source"].startswith("haoshenqi")
    finally:
        tmp.cleanup()


def test_holiday_flag_mapping() -> None:
    calendar, lib, online, tmp = make_manager(
        online_verdicts={D_FUTURE: CalendarVerdict.KNOWN_HOLIDAY}
    )
    try:
        assert calendar.holiday_flag(D_FUTURE) is True
        assert calendar.holiday_flag(D_WORKDAY) is False  # lib 覆盖内周一
    finally:
        tmp.cleanup()


def test_market_session_integration_unchanged() -> None:
    """market_session 经门面后：既有语义不变（周内在 lib 覆盖内）"""
    assert market_session.is_trading_day(D_WORKDAY) is True
    assert market_session.is_trading_day(datetime.date(2025, 10, 1)) is False
    assert market_session.is_trading_day(D_SATURDAY) is False  # 周六恒休市
    assert market_session.is_trading_day(D_FUTURE) is True  # 2027 周二，weekly 兜底


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
