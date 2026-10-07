"""通知阶段 D：波动 / 每日摘要 / 节后缺口三个触发器测试。

按已拍板的默认参数验证：

- 波动：1% 两档阈值（≥1% 提醒 / ≥2.5% 强提醒）、双基准取偏离大者、
  冷却 60 分钟（强提醒不受冷却限制，但偏离未加深/未反转不重发）、
  SILENT 不发；
- 摘要：20:00 触发、每天一条、SILENT 不发、INTL_ONLY 附假期累计与持仓；
- 缺口：仅「法定节假日 + 明日交易日 + INTL_ONLY」的到点时刻发，每天一条。

运行
----
    cd backend
    python -m test.test_notification_triggers
"""

import datetime
from unittest import mock

from channels.base import KIND_DIGEST
from service.send_gate import GateDecision
from service.triggers import (
    DailyDigestTrigger,
    ReopenGapTrigger,
    TickContext,
    VolatilityTrigger,
)
from utils.market_session import SendPolicy, Session

WED_19 = datetime.datetime(2026, 10, 7, 19, 30)  # 假期最后一天（周三）
WED_20 = datetime.datetime(2026, 10, 7, 20, 5)


class FakeSettings:
    def __init__(self, config=None):
        self._config = config or {}

    def get_advice_config(self):
        return dict(self._config)

    def get_symbol_name_map(self):
        return {"gds_AUTD": "黄金T+D", "hf_XAU": "伦敦金"}


class FakePriceMapper:
    def __init__(self, series=None):
        self._series = series or []

    def get_price_series(self, symbol, hours):
        return self._series


class FakePortfolioMapper:
    def __init__(self, lots=None):
        self._lots = lots or []

    def list_lots(self, symbol):
        return self._lots

    def list_sales(self, symbol):
        return []


HOLIDAY_LOT = [
    {
        "id": 1,
        "symbol": "gds_AUTD",
        "grams": 50.0,
        "price_per_gram": 900.0,
        "trade_date": "2026-01-10",
        "is_opening": 0,
    }
]


def normal_tick(**overrides) -> TickContext:
    decision = GateDecision(
        policy=SendPolicy.INTL_ONLY,
        sge=Session.HOLIDAY,
        intl=Session.OPEN,
        allowed=True,
        reason="",
        detail="假期休市，国际金开市",
    )
    defaults = {
        "at": WED_20,
        "decision": decision,
        "prices_data": {"gds_AUTD": {"price": 900.0}},  # 冻结的节前收盘
        "main_symbol": "gds_AUTD",
        "market_symbol": "hf_XAU",
        "market_price": 902.0,
        "london_cny": 902.0,
        "london_usd": 2330.0,
        "valuation_note": "休市期间以国际金折算价估算，可能与国内开盘价存在偏差",
    }
    defaults.update(overrides)
    return TickContext(**defaults)


class FakeCalendar:
    def __init__(self, flags):
        self._flags = flags

    def holiday_flag(self, day):
        return self._flags.get(day)


# ==================== VolatilityTrigger ====================


def test_volatility_first_tick_seeds_baseline_only() -> None:
    trigger = VolatilityTrigger(FakeSettings())
    outcome = trigger.evaluate(normal_tick(market_price=900.0))
    assert outcome.events == [], "首个 tick 只建基线"


def test_volatility_level1_emits_within_threshold() -> None:
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=900.0))
    outcome = trigger.evaluate(normal_tick(market_price=910.0))  # +1.11%
    assert len(outcome.events) == 1
    ev = outcome.events[0]
    assert ev.notification is not None
    assert ev.notification.alert_level == "warning"
    assert ev.urgency == "medium"
    assert ev.cooldown_minutes == 60.0
    assert "较上次提醒" in ev.notification.fields
    assert ev.notification.fields["较上次提醒"] == "+1.11%"
    assert ev.notification.summary.startswith("黄金上涨")


def test_volatility_cooldown_blocks_level1() -> None:
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=900.0))
    assert trigger.evaluate(normal_tick(market_price=910.0)).events
    # 30 分钟后再次超过 1%（910 基线 → 920）——仍处冷却期
    later = normal_tick(
        at=WED_20 + datetime.timedelta(minutes=30), market_price=920.0
    )
    assert trigger.evaluate(later).events == []


def test_volatility_critical_bypasses_cooldown() -> None:
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=900.0))
    trigger.evaluate(normal_tick(market_price=910.0))
    # 8 分钟后暴涨到 935（较基线 910 ≈ +2.75% ≥ 2.5%）
    critical = normal_tick(
        at=WED_20 + datetime.timedelta(minutes=8), market_price=935.0
    )
    outcome = trigger.evaluate(critical)
    assert len(outcome.events) == 1
    ev = outcome.events[0]
    assert ev.notification.alert_level == "critical"
    assert ev.urgency == "high"
    assert ev.cooldown_minutes == 0.0


def test_volatility_critical_no_refire_while_loitering() -> None:
    """价格在阈值附近徘徊时强提醒不重发（曾每 10 秒刷一条企业微信）"""
    trigger = VolatilityTrigger(FakeSettings())
    # 节前收盘 900：876.0 → -2.67%，首次强提醒
    first = trigger.evaluate(normal_tick(market_price=876.0))
    assert len(first.events) == 1

    # 徘徊：-2.72% / -2.61%，偏离未加深 → 不再重发
    assert trigger.evaluate(normal_tick(market_price=875.5)).events == []
    assert trigger.evaluate(normal_tick(market_price=876.5)).events == []


def test_volatility_critical_refires_when_deepened() -> None:
    """偏离较上次强提醒加深 ≥ 0.5pp → 重发"""
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=876.0))  # -2.67% 首发
    outcome = trigger.evaluate(normal_tick(market_price=866.0))  # -3.78%，加深 1.1pp
    assert len(outcome.events) == 1
    assert outcome.events[0].notification.alert_level == "critical"


def test_volatility_critical_refires_when_flipped() -> None:
    """方向反转（跌转涨越过阈值）→ 立即重发"""
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=876.0))  # -2.67% 首发下跌
    outcome = trigger.evaluate(normal_tick(market_price=930.0))  # +3.33% 反转上涨
    assert len(outcome.events) == 1
    assert "上涨" in outcome.events[0].notification.summary


def test_volatility_critical_refires_after_first_level1() -> None:
    """level 1 之后的首次 level 2 必然发出（level 1 不参与去噪记账）"""
    trigger = VolatilityTrigger(FakeSettings())
    trigger.evaluate(normal_tick(market_price=900.0))  # 建基线
    trigger.evaluate(normal_tick(market_price=910.0))  # +1.11% level 1
    outcome = trigger.evaluate(normal_tick(market_price=935.0))  # +2.75% level 2
    assert len(outcome.events) == 1


def test_volatility_double_basis_prefers_larger_deviation() -> None:
    """长假首日：基线尚未建立偏离，但较节前收盘已超阈值 → 立即提醒"""
    trigger = VolatilityTrigger(FakeSettings())
    # 首个 tick：基线=920，但较节前收盘 900 已 +2.2%
    outcome = trigger.evaluate(normal_tick(market_price=920.0))
    assert len(outcome.events) == 1
    fields = outcome.events[0].notification.fields
    assert "较节前收盘" in fields, "应选偏离更大的节前收盘基准"
    assert fields["较节前收盘"] == "+2.22%"


def test_volatility_disabled_or_silent() -> None:
    trigger = VolatilityTrigger(FakeSettings({"volatility_enabled": False}))
    assert trigger.evaluate(normal_tick(market_price=950.0)).events == []

    trigger2 = VolatilityTrigger(FakeSettings())
    silent = normal_tick(
        decision=GateDecision(
            policy=SendPolicy.SILENT,
            sge=Session.WEEKEND,
            intl=Session.WEEKEND,
            allowed=False,
            reason="silent",
            detail="双休市",
        )
    )
    assert trigger2.evaluate(silent).events == []


# ==================== DailyDigestTrigger ====================


def make_digest_trigger(config=None, lots=None, series=None):
    settings = FakeSettings(config)
    price_mapper = FakePriceMapper(
        series or [(WED_20 - datetime.timedelta(hours=24), 890.0), (WED_20, 902.0)]
    )
    portfolio = FakePortfolioMapper(lots or HOLIDAY_LOT)
    return DailyDigestTrigger(settings, price_mapper, portfolio)


def test_digest_before_time_not_sent() -> None:
    trigger = make_digest_trigger()
    outcome = trigger.evaluate(normal_tick(at=WED_19))
    assert outcome.events == []


def test_digest_emits_once_per_day_with_position() -> None:
    trigger = make_digest_trigger()
    outcome = trigger.evaluate(normal_tick())
    assert len(outcome.events) == 1
    ev = outcome.events[0]
    assert ev.kind == KIND_DIGEST or ev.notification.kind == KIND_DIGEST
    fields = ev.notification.fields
    assert "当前价格" not in fields, "当前价格由模板固定行展示，不进 fields"
    assert "24 小时涨跌" in fields
    assert "较节前收盘" in fields, "INTL_ONLY 附假期累计"
    assert fields["持仓"] == "50g", "有持仓时报持仓与浮盈"
    assert ev.notification.alert_level == "info"
    # 同日第二条不发
    assert trigger.evaluate(normal_tick(at=WED_20 + datetime.timedelta(minutes=10))).events == []


def test_digest_silent_and_normal_paths() -> None:
    trigger = make_digest_trigger()
    silent = normal_tick(
        decision=GateDecision(
            policy=SendPolicy.SILENT,
            sge=Session.WEEKEND,
            intl=Session.WEEKEND,
            allowed=False,
            reason="silent",
            detail="双休市",
        )
    )
    assert trigger.evaluate(silent).events == []

    normal = normal_tick(
        decision=GateDecision(
            policy=SendPolicy.NORMAL,
            sge=Session.OPEN,
            intl=Session.OPEN,
            allowed=True,
            reason="",
            detail="交易日",
        ),
        market_symbol=None,
        market_price=905.0,
    )
    outcome = trigger.evaluate(normal)
    assert len(outcome.events) == 1
    assert "较节前收盘" not in outcome.events[0].notification.fields


# ==================== ReopenGapTrigger ====================


def make_gap_trigger(config=None, calendar_flags=None, lots=None):
    settings = FakeSettings(config)
    portfolio = FakePortfolioMapper(lots or HOLIDAY_LOT)
    flags = (
        calendar_flags if calendar_flags is not None else {WED_20.date(): True}
    )
    calendar = FakeCalendar(flags)
    return ReopenGapTrigger(
        settings, FakePriceMapper(), portfolio, calendar=calendar
    )


def test_gap_emits_on_holiday_last_evening() -> None:
    trigger = make_gap_trigger()
    outcome = trigger.evaluate(normal_tick())
    assert len(outcome.events) == 1
    ev = outcome.events[0]
    fields = ev.notification.fields
    assert fields["节前收盘"] == "¥900.00/g"
    assert fields["假期累计"] == "+0.22%"
    assert fields["预计开盘方向"] == "高开"
    assert "偏差" in fields["说明"]
    assert ev.notification.alert_level == "warning"


def test_gap_skips_non_holiday_and_once_per_day() -> None:
    trigger = make_gap_trigger(calendar_flags={})  # 今天不是法定节假日（如普通周末）
    assert trigger.evaluate(normal_tick()).events == []

    trigger2 = make_gap_trigger()
    assert trigger2.evaluate(normal_tick()).events
    assert trigger2.evaluate(normal_tick(at=WED_20 + datetime.timedelta(minutes=5))).events == []


def test_gap_skips_when_tomorrow_not_trading() -> None:
    import service.triggers.reopen_gap as gap_module

    trigger = make_gap_trigger()
    with mock.patch.object(gap_module, "is_trading_day", lambda day: False):
        outcome = trigger.evaluate(normal_tick())
    assert outcome.events == [], "明天不是交易日不预告"


def test_gap_only_during_intl_only() -> None:
    trigger = make_gap_trigger()
    normal = normal_tick(
        decision=GateDecision(
            policy=SendPolicy.NORMAL,
            sge=Session.OPEN,
            intl=Session.OPEN,
            allowed=True,
            reason="",
            detail="交易日",
        ),
        market_symbol=None,
    )
    assert trigger.evaluate(normal).events == []


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
