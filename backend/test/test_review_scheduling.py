"""阶段 4 的调度部分：到点判断、回访价格回填、以及它接进监控循环。

最重要的一条是 **回访必须取「目标日期当时」的价格**，而不是「现在」的价格。
如果停机几天后再回填，用最新价会把 T+1 写成 T+5 的价格 —— 这种错误不报错，
只会静默污染「建议准不准」的统计，是这类功能最容易埋下的坑。

运行
----
    cd backend
    python -m test.test_review_scheduling
"""

import contextlib
import datetime
import logging
import os
import tempfile

import service.monitor_service as monitor_module
from mapper.advice_mapper import AdviceMapper
from mapper.price_mapper import PriceMapper
from service.advice.advice_engine import AdviceEngine, _review_target_timestamp
from service.monitor_service import REVIEW_REFRESH_SECONDS, MonitorService
from service.send_gate import GateDecision
from utils.due_timer import DueTimer
from utils.market_session import SendPolicy, Session
from utils.time_utils import CHINA_TZ, now

_test_logger = logging.getLogger("test.review")
_test_logger.addHandler(logging.NullHandler())
_test_logger.propagate = False

WED = datetime.datetime(2025, 9, 24, 10, 0)
SAT = datetime.datetime(2025, 9, 27, 10, 0)


@contextlib.contextmanager
def assert_raises(exc_type: type[BaseException], match: str | None = None):
    try:
        yield
    except exc_type as exc:
        if match is not None and match not in str(exc):
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


# ==================== 1. DueTimer ====================


def test_due_timer_first_run_is_due() -> None:
    timer = DueTimer("测试", 60)
    assert timer.is_due(WED) is True, "从没跑过应当算到点（启动后立刻补齐）"
    assert timer.is_due(WED, never_run_is_due=False) is False


def test_due_timer_respects_interval() -> None:
    timer = DueTimer("测试", 60)
    timer.mark(WED)
    assert timer.is_due(WED) is False
    assert timer.is_due(WED + datetime.timedelta(seconds=59)) is False
    assert timer.is_due(WED + datetime.timedelta(seconds=60)) is True
    assert timer.is_due(WED + datetime.timedelta(seconds=600)) is True


def test_due_timer_disabled() -> None:
    timer = DueTimer("测试", 0)
    assert timer.enabled is False
    assert timer.is_due(WED) is False, "间隔为 0 表示不启用"


def test_due_timer_seconds_until_due() -> None:
    timer = DueTimer("测试", 100)
    assert timer.seconds_until_due(WED) == 0.0, "从没跑过时视为已到点"
    timer.mark(WED)
    assert timer.seconds_until_due(WED + datetime.timedelta(seconds=40)) == 60.0
    assert timer.seconds_until_due(WED + datetime.timedelta(seconds=500)) == 0.0


def test_due_timer_reset_and_set_interval() -> None:
    timer = DueTimer("测试", 60)
    timer.mark(WED)
    assert timer.is_due(WED) is False

    timer.reset()
    assert timer.is_due(WED) is True
    assert timer.last_run is None

    # 改间隔不重置上次运行时间，避免「改一次配置就立刻触发一次」
    timer.mark(WED)
    timer.set_interval(3600)
    assert timer.is_due(WED + datetime.timedelta(seconds=61)) is False
    assert timer.is_due(WED + datetime.timedelta(seconds=3600)) is True


# ==================== 2. 取「当时」的价格 ====================


def seed_prices(mapper: PriceMapper, points: list[tuple[int, float]], symbol="gds_AUTD"):
    with mapper._connect() as conn:
        conn.execute("DELETE FROM prices WHERE symbol = ?", (symbol,))
        for ts, price in points:
            conn.execute(
                "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                (symbol, price, ts),
            )


def test_get_price_near_prefers_last_before() -> None:
    with temp_db("near.db") as db:
        mapper = PriceMapper(db_file=db)
        seed_prices(mapper, [(1000, 900.0), (2000, 910.0), (3000, 920.0)])
        assert mapper.get_price_near("gds_AUTD", 2500) == 910.0
        assert mapper.get_price_near("gds_AUTD", 2000) == 910.0, "恰好命中"
        assert mapper.get_price_near("gds_AUTD", 5000) == 920.0, "之后没有数据则取最后一条"


def test_get_price_near_falls_back_to_next() -> None:
    with temp_db("near2.db") as db:
        mapper = PriceMapper(db_file=db)
        seed_prices(mapper, [(2000, 910.0), (3000, 920.0)])
        assert mapper.get_price_near("gds_AUTD", 1000) == 910.0, "早于全部数据时取最早一条"


def test_get_price_near_missing_symbol() -> None:
    with temp_db("near3.db") as db:
        mapper = PriceMapper(db_file=db)
        assert mapper.get_price_near("gds_AUTD", 1000) is None


def test_get_price_near_differs_from_latest() -> None:
    """这正是必须区分两者的原因"""
    with temp_db("near4.db") as db:
        mapper = PriceMapper(db_file=db)
        seed_prices(mapper, [(1000, 900.0), (2000, 910.0), (99999, 1100.0)])
        assert mapper.get_price_near("gds_AUTD", 1500) == 900.0
        assert mapper.get_latest_price("gds_AUTD") == 1100.0


# ==================== 3. 回访回填 ====================


def make_engine(db: str, price_db: str) -> AdviceEngine:
    engine = object.__new__(AdviceEngine)
    engine.advice_mapper = AdviceMapper(db_file=db)
    engine.price_mapper = PriceMapper(db_file=price_db)
    return engine


def insert_advice(mapper: AdviceMapper, created_at: str, symbol="gds_AUTD") -> int:
    return mapper.insert_advice(
        {
            "kind": "pre_purchase",
            "action": "BUY_NOW",
            "symbol": symbol,
            "price_at_advice": 900.0,
            "created_at": created_at,
        }
    )


def test_review_target_timestamp() -> None:
    ts = _review_target_timestamp("2025-09-24 10:00:00", 1)
    expected = int(
        datetime.datetime(2025, 9, 25, 10, 0, tzinfo=CHINA_TZ).timestamp()
    )
    assert ts == expected
    assert _review_target_timestamp("not-a-date", 1) is None


def test_refresh_reviews_uses_target_date_price() -> None:
    """核心断言：回填的是「目标日期当时」的价格，不是最新价"""
    with temp_db("review_advice.db") as advice_db, temp_db("review_price.db") as price_db:
        mapper = AdviceMapper(db_file=advice_db)
        created = datetime.datetime(2025, 9, 24, 10, 0, tzinfo=CHINA_TZ)
        advice_id = insert_advice(mapper, created.strftime("%Y-%m-%d %H:%M:%S"))

        price_mapper = PriceMapper(db_file=price_db)
        seed_prices(
            price_mapper,
            [
                (int(created.timestamp()), 900.0),
                (int((created + datetime.timedelta(days=1)).timestamp()), 918.0),
                (int((created + datetime.timedelta(days=2)).timestamp()), 930.0),
                # 15 天后价格已经跌到 800 —— 最新价，但绝不是 T+1 的价格
                (int((created + datetime.timedelta(days=15)).timestamp()), 800.0),
            ],
        )

        engine = make_engine(advice_db, price_db)
        # 二十天后再跑回填（模拟停机、很久没跑）
        reference = created + datetime.timedelta(days=20)
        result = engine.refresh_reviews(reference)

        stored = mapper.get_advice(advice_id)
        assert stored["price_t1"] == 918.0, "T+1 必须是发出后一天的价格，不能是最新价 800"
        assert stored["price_t7"] == 930.0, "T+7 取该时点之前最近的一条（+2 天）"
        assert stored["price_t30"] is None, "还没到期"
        assert result["filled"] == 2, f"T+1 与 T+7 都应回填，实际 {result}"
        assert stored["reviewed_at"]


def test_refresh_reviews_skips_when_no_price_at_target() -> None:
    with temp_db("skip_advice.db") as advice_db, temp_db("skip_price.db") as price_db:
        mapper = AdviceMapper(db_file=advice_db)
        created = datetime.datetime(2025, 9, 24, 10, 0, tzinfo=CHINA_TZ)
        insert_advice(mapper, created.strftime("%Y-%m-%d %H:%M:%S"))
        # 价格库里完全没有数据
        engine = make_engine(advice_db, price_db)

        reference = created + datetime.timedelta(days=2)
        result = engine.refresh_reviews(reference)
        assert result["checked"] == 1
        assert result["filled"] == 0
        assert result["skipped"] == 1, "缺价应记为 skipped，而不是静默算成功"


def test_refresh_reviews_is_idempotent() -> None:
    with temp_db("idem_advice.db") as advice_db, temp_db("idem_price.db") as price_db:
        mapper = AdviceMapper(db_file=advice_db)
        created = datetime.datetime(2025, 9, 24, 10, 0, tzinfo=CHINA_TZ)
        insert_advice(mapper, created.strftime("%Y-%m-%d %H:%M:%S"))
        seed_prices(
            PriceMapper(db_file=price_db),
            [
                (int(created.timestamp()), 900.0),
                (int((created + datetime.timedelta(days=1)).timestamp()), 918.0),
            ],
        )
        engine = make_engine(advice_db, price_db)
        reference = created + datetime.timedelta(days=1, hours=1)

        assert engine.refresh_reviews(reference)["filled"] == 1
        assert engine.refresh_reviews(reference)["filled"] == 0, "已回填的不应重复写"


def test_refresh_reviews_respects_horizon() -> None:
    with temp_db("hz_advice.db") as advice_db, temp_db("hz_price.db") as price_db:
        mapper = AdviceMapper(db_file=advice_db)
        created = datetime.datetime(2025, 9, 24, 10, 0, tzinfo=CHINA_TZ)
        insert_advice(mapper, created.strftime("%Y-%m-%d %H:%M:%S"))
        seed_prices(
            PriceMapper(db_file=price_db),
            [(int(created.timestamp()), 900.0), (int((created + datetime.timedelta(days=1)).timestamp()), 918.0)],
        )
        engine = make_engine(advice_db, price_db)

        # 只过了几小时 → 谁都没到期
        assert engine.refresh_reviews(created + datetime.timedelta(hours=3))["checked"] == 0
        # 过了一天 → T+1 到期
        assert engine.refresh_reviews(created + datetime.timedelta(days=1, hours=1))["checked"] == 1


# ==================== 4. 接进监控循环 ====================


class FakeAdviceEngineForReview:
    def __init__(self, result=None, fail=False):
        self.result = result or {"checked": 0, "filled": 0, "skipped": 0}
        self.fail = fail
        self.calls = 0

    def refresh_reviews(self, at=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return self.result


def make_monitor(engine) -> MonitorService:
    monitor = object.__new__(MonitorService)
    monitor.logger = _test_logger
    monitor.main_symbol = "gds_AUTD"
    monitor.advice_engine = engine
    monitor._review_timer = DueTimer("回访价格回填", REVIEW_REFRESH_SECONDS)
    return monitor


@contextlib.contextmanager
def frozen_monitor(at: datetime.datetime):
    from test.test_market_session import frozen

    with frozen(at):
        saved = monitor_module.now
        monitor_module.now = lambda: at
        try:
            yield
        finally:
            monitor_module.now = saved


def test_monitor_refreshes_reviews_when_due() -> None:
    engine = FakeAdviceEngineForReview({"checked": 3, "filled": 2, "skipped": 1})
    monitor = make_monitor(engine)
    with frozen_monitor(WED):
        monitor._refresh_reviews_if_due()
    assert engine.calls == 1

    # 同一次巡检周期内不应重复
    with frozen_monitor(WED):
        monitor._refresh_reviews_if_due()
    assert engine.calls == 1

    # 过了间隔才再跑
    with frozen_monitor(WED + datetime.timedelta(seconds=REVIEW_REFRESH_SECONDS)):
        monitor._refresh_reviews_if_due()
    assert engine.calls == 2


def test_monitor_review_failure_does_not_break_tick() -> None:
    engine = FakeAdviceEngineForReview(fail=True)
    monitor = make_monitor(engine)
    with frozen_monitor(WED):
        monitor._refresh_reviews_if_due()  # 不应抛出
    assert engine.calls == 1


def test_monitor_refreshes_reviews_while_market_silent() -> None:
    """回填读的是历史价格，与是否休市无关 —— 周末正是补齐的好时机"""
    engine = FakeAdviceEngineForReview({"checked": 1, "filled": 1, "skipped": 0})
    monitor = make_monitor(engine)
    silent = GateDecision(
        policy=SendPolicy.SILENT,
        sge=Session.WEEKEND,
        intl=Session.WEEKEND,
        allowed=False,
        reason="silent",
        detail="周末休市",
    )
    assert silent.allowed is False
    with frozen_monitor(SAT):
        monitor._refresh_reviews_if_due()
    assert engine.calls == 1, "休市期间也应回填回访价格"


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
