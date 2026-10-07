"""bug 修复回归测试 —— 防止本轮修复被未来重构回退。

覆盖：
1. 触发器接线（_tick 必须评估全部注册触发器 —— 曾整体失效）
2. INTL_ONLY 指标口径（快照与现价必须同单位 —— 曾相差一个数量级）
3. 在线日历列表响应兜底（不得取 data[0] 张冠李戴）
4. 日历缓存脏值自愈
5. alert_level 显式语义（显式 warning 不降级，未指定降为 info）
6. PriceSnapshot.scaled / update_status(suppressed_reason)
"""

import contextlib
import tempfile
import types
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from channels.base import KIND_VOLATILITY, NotificationData
from mapper.advice_mapper import AdviceMapper
from mapper.calendar_cache_mapper import CalendarCacheMapper
from mapper.price_mapper import PriceSnapshot
from providers.calendar.base import CalendarVerdict
from providers.calendar.online import OnlineCalendarProvider
from service.advice.advice_engine import AdviceEngine
from service.monitor_service import (
    LOG_CLEANUP_SECONDS,
    REVIEW_REFRESH_SECONDS,
    SETTINGS_REFRESH_SECONDS,
    MonitorService,
)
from service.triggers.base import TickContext, Trigger, TriggerOutcome, TriggerRegistry
from service.triggers.notify_common import TRIGGER_CONFIG_DEFAULTS
from utils.due_timer import DueTimer
from utils.logger import get_logger
from utils.time_utils import now

_test_logger = get_logger("TestBugfixRegression")


# ==================== 1. 触发器接线 ====================


class SpyTrigger(Trigger):
    """记录 evaluate 调用的触发器"""

    def __init__(self, name: str):
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        self.calls += 1
        return TriggerOutcome()


class FakePriceService:
    def fetch_all_gold_prices(self, symbols):
        return {symbol: {"price": 900.0} for symbol in symbols}


class FakePriceMapper:
    def save_price(self, symbol, price):
        return None


class FakeSettings:
    def get_monitor_config(self):
        return {"main_symbol": "gds_AUTD", "monitor_symbols": ["gds_AUTD"], "check_interval": 10}

    def get_ai_config(self):
        return {"check_interval_minutes": 5}

    def get_log_config(self):
        return {"keep_days": 30}


class FakeSendGate:
    """永远放行的闸门"""

    class _Decision:
        allowed = True
        policy = None
        reason = ""
        detail = ""

    def policy_decision(self):
        return self._Decision()


class FakeNotificationService:
    def send_advice(self, *args, **kwargs):
        return True

    def send(self, *args, **kwargs):
        return True


def make_wired_monitor(triggers: list[Trigger]) -> MonitorService:
    """构造接线受控的 MonitorService（绕过 __init__，全部用假件）"""
    monitor = object.__new__(MonitorService)
    monitor.logger = _test_logger
    monitor.settings = FakeSettings()
    monitor.price_mapper = FakePriceMapper()
    monitor.price_service = FakePriceService()
    monitor.notification_service = FakeNotificationService()
    monitor.send_gate = FakeSendGate()
    monitor.trigger_registry = TriggerRegistry(triggers)
    monitor.main_symbol = "gds_AUTD"
    monitor.monitor_symbols = ["gds_AUTD"]
    monitor.check_interval = 10
    monitor.ai_check_interval_minutes = 5
    monitor.check_count = 0
    monitor.alert_count = 0
    monitor.start_time = now()
    monitor._last_suppressed = None
    at = now()
    # 全部定时器预标记：本 tick 不触发设置刷新/回访/日志清理
    monitor._settings_timer = DueTimer("设置刷新", SETTINGS_REFRESH_SECONDS)
    monitor._review_timer = DueTimer("回访价格回填", REVIEW_REFRESH_SECONDS)
    monitor._cleanup_timer = DueTimer("日志清理", LOG_CLEANUP_SECONDS)
    for timer in (monitor._settings_timer, monitor._review_timer, monitor._cleanup_timer):
        timer.mark(at)
    return monitor


def test_tick_evaluates_all_registered_triggers() -> None:
    """_tick 必须通过 registry 评估全部触发器（曾遗漏 → 波动/摘要/缺口整体失效）"""
    spies = [SpyTrigger(f"t{i}") for i in range(5)]
    monitor = make_wired_monitor(spies)

    monitor._tick()

    assert all(s.calls == 1 for s in spies), (
        "每个注册触发器都应被评估一次"
    )
    assert monitor.check_count == 1


def test_tick_evaluates_registry_even_when_gate_closed() -> None:
    """闸门关闭时 registry 仍应被调用（各触发器内部自行服从闸门）"""

    class ClosedGate(FakeSendGate):
        class _Decision:
            allowed = False
            policy = None
            reason = "closed"
            detail = ""

    spies = [SpyTrigger("t") for _ in range(3)]
    monitor = make_wired_monitor(spies)
    monitor.send_gate = ClosedGate()

    monitor._tick()

    assert all(s.calls == 1 for s in spies)


# ==================== 2. INTL_ONLY 指标口径 ====================


class FakeEnginePriceMapper:
    """建议引擎用的假 price_mapper：只提供快照"""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot

    def get_check_snapshot(self, symbol):
        return self.snapshot


class FakePortfolioMapper:
    def list_lots(self, symbol=None):
        return []

    def list_sales(self, symbol=None):
        return []

    def list_plans(self, symbol=None):
        return []


class FakeSettings2:
    def __init__(self, config=None):
        self._config = config or {}

    def get_symbol_name_map(self):
        return {}

    def get_advice_config(self):
        return self._config

    def get_alert_config(self):
        return {}

    def get_prefs(self):
        return {}


def make_engine(snapshot, config=None) -> AdviceEngine:
    engine = object.__new__(AdviceEngine)
    engine.settings = FakeSettings2(config)
    engine.price_mapper = FakeEnginePriceMapper(snapshot)
    engine.portfolio_mapper = FakePortfolioMapper()
    engine.advisor = None
    engine.entry_evaluator = types.SimpleNamespace(
        evaluate=lambda symbol, price, **kw: None
    )
    return engine


def test_intl_only_snapshot_scaled_to_cny_per_gram() -> None:
    """INTL_ONLY：快照是美元/盎司、现价是折算 ¥/g —— 指标必须换算同口径。

    修复前 pct_from_3m_low ≈ -87%（跨数量级），恒命中「远低于 3 个月低位」假信号。
    """
    # 美元/盎司量级的序列：3 个月低点 4100，近期 4130 附近
    base = now() - timedelta(hours=2)
    prices = [(base + timedelta(minutes=i), 4120.0 + i) for i in range(10)]
    snapshot = PriceSnapshot(prices, [4130.0] * 30, min_3m=4100.0, min_6m=4050.0)
    engine = make_engine(snapshot)

    london_usd = 4130.0
    converted_cny = 541.18  # 折算 ¥/g
    computed = engine.compute(
        "gds_AUTD",
        converted_cny,
        london_cny=converted_cny,
        london_usd=london_usd,
        market_symbol="hf_XAU",
        use_llm=False,
    )

    market = computed.draft.evidence["market"]
    pct_3m = market["pct_from_3m_low"]
    # 折算后 3m 低点 4100*541.18/4130 ≈ 536.9，现价 541.18 → 约 +0.8%
    assert abs(pct_3m) < 10, (
        f"INTL_ONLY 指标应与现价同口径（得到 {pct_3m}%，跨单位错配时会达 -80%）"
    )
    # 现价字段仍保持 ¥/g 口径（供持仓估值与消息渲染）
    assert market["current_price"] == pytest.approx(converted_cny)


def test_price_snapshot_scaled() -> None:
    base = now() - timedelta(hours=1)
    snap = PriceSnapshot(
        [(base, 4000.0), (base, 4100.0)], [4000.0] * 20, min_3m=3900.0, min_6m=3800.0
    )
    scaled = snap.scaled(0.5)
    assert scaled.prices_last_n(10) == [2000.0, 2050.0]
    assert scaled.ma(20) == pytest.approx(2000.0)
    assert scaled.min_3m == pytest.approx(1950.0)
    assert scaled.min_6m == pytest.approx(1900.0)
    # 原快照不受影响
    assert snap.ma(20) == pytest.approx(4000.0)


# ==================== 3. 在线日历列表响应兜底 ====================


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_online_calendar_list_response_matching_day() -> None:
    with patch("providers.calendar.online.requests.get") as mock_get:
        mock_get.return_value = FakeResp(
            [
                {"date": "2027-01-01", "status": 3},
                {"date": "2027-01-02", "status": 0},
            ]
        )
        provider = OnlineCalendarProvider()
        verdict = provider.holiday_info(date(2027, 1, 1))
    assert verdict is CalendarVerdict.KNOWN_HOLIDAY


def test_online_calendar_list_response_without_matching_day_is_unknown() -> None:
    """列表中没有目标日期时必须 UNKNOWN 回退，不得取 data[0] 张冠李戴"""
    with patch("providers.calendar.online.requests.get") as mock_get:
        # 全部是其它日期的记录（模拟未发布年份的响应）
        mock_get.return_value = FakeResp([{"date": "2027-01-01", "status": 3}])
        provider = OnlineCalendarProvider()
        verdict = provider.holiday_info(date(2027, 5, 1))
    assert verdict is CalendarVerdict.UNKNOWN


def test_online_calendar_list_response_non_dict_items_is_unknown() -> None:
    with patch("providers.calendar.online.requests.get") as mock_get:
        mock_get.return_value = FakeResp(["2027-01-01", "2027-01-02"])
        provider = OnlineCalendarProvider()
        verdict = provider.holiday_info(date(2027, 1, 1))
    assert verdict is CalendarVerdict.UNKNOWN


# ==================== 4. 日历缓存脏值自愈 ====================


def test_calendar_cache_dirty_verdict_self_heals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mapper = CalendarCacheMapper(db_file=f"{tmp}/calendar.db")
        day = date(2027, 6, 1)
        mapper.put(day, "holiday", "haoshenqi")
        # 模拟脏值（手工编辑/旧版本写入）
        with mapper._session() as conn:
            conn.execute(
                "UPDATE holiday_cache SET verdict = 'bogus' WHERE day = ?",
                (day.isoformat(),),
            )
        assert mapper.get(day) is None, "脏值应返回 None（回退在线源）"
        assert mapper.get(day) is None, "脏值应已被删除，不再反复触发"
        # 正常值不受影响
        mapper.put(day, "workday", "haoshenqi")
        assert mapper.get(day) == "workday"


# ==================== 5. alert_level 显式语义 ====================


def test_notification_send_level_semantics() -> None:
    from service.notification_service import NotificationService

    service = object.__new__(NotificationService)
    service.settings = types.SimpleNamespace(
        get_notification_strategy=lambda: {"stop_on_first_success": True},
        get_notification_channels=lambda: [],  # 无渠道：提前返回，但降级已发生
    )
    service.stats_service = types.SimpleNamespace(log_send=lambda **kw: None)

    explicit = NotificationData(
        kind=KIND_VOLATILITY, alert_level="warning", summary="x"
    )
    service.send(explicit)
    assert explicit.alert_level == "warning", "显式 warning 不应被降级"

    critical = NotificationData(
        kind=KIND_VOLATILITY, alert_level="critical", summary="x"
    )
    service.send(critical)
    assert critical.alert_level == "critical"

    unspecified = NotificationData(kind=KIND_VOLATILITY, summary="x")
    assert unspecified.alert_level is None
    service.send(unspecified)
    assert unspecified.alert_level == "info", "未指定级别应降为 info"


# ==================== 6. update_status 支持 suppressed_reason ====================


def test_update_status_sets_suppressed_reason() -> None:
    with temp_db("advice.db") as db:
        mapper = AdviceMapper(db_file=db)
        advice_id = mapper.insert_advice(
            {
                "kind": "advice",
                "action": "HOLD",
                "symbol": "gds_AUTD",
            }
        )
        assert mapper.update_status(advice_id, "suppressed", suppressed_reason="send_failed")
        row = mapper.get_advice(advice_id)
        assert row["status"] == "suppressed"
        assert row["suppressed_reason"] == "send_failed"
        # 不传 reason 时不应覆盖
        mapper.update_status(advice_id, "delivered")
        row = mapper.get_advice(advice_id)
        assert row["status"] == "delivered"
        assert row["suppressed_reason"] == "send_failed"


@contextlib.contextmanager
def temp_db(name: str):
    with tempfile.TemporaryDirectory() as tmp:
        yield __import__("os").path.join(tmp, name)


def test_trigger_config_defaults_cover_keys() -> None:
    """触发器配置默认值完整（配置读取失败时功能不至于失明）"""
    assert set(TRIGGER_CONFIG_DEFAULTS) >= {
        "volatility_enabled",
        "volatility_trigger_pct",
        "volatility_critical_pct",
        "volatility_cooldown_minutes",
        "digest_enabled",
        "digest_time",
        "reopen_gap_enabled",
        "reopen_gap_time",
    }
