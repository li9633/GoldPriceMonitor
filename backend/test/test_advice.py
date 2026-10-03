"""建议域测试：指标提取 + 信号 + 策略 + 持久化 + 引擎编排。

覆盖 `docs/refactor-plan.md` §4 的设计约定：
规则出事实（信号可单测）、LLM 只出表述（失败自动回退）、建议必须可回溯。

运行
----
    cd backend
    python -m test.test_advice
"""

import contextlib
import os
import sqlite3
import tempfile
from datetime import date, timedelta

from mapper.advice_mapper import AdviceMapper
from mapper.price_mapper import PriceSnapshot
from models.advice import (
    AdviceAction,
    AdviceKind,
    AdvicePrefs,
    AdviceStatus,
)
from service.advice import signals as signal_rules
from service.advice.advice_engine import AdviceEngine
from service.advice.context import (
    AdviceContext,
    MarketIndicators,
    build_plan_states,
)
from service.advice.strategies import build_advice, select_kind
from service.position import compute_position, summarize_plans
from utils.time_utils import now

DAY = date(2026, 1, 10)


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


# ==================== 构造工具 ====================


def make_snapshot(prices=None, ma_prices=None, min_3m=None, min_6m=None):
    base = now() - timedelta(hours=2)
    if prices is None:
        prices = [(base + timedelta(minutes=i), 900.0 + i) for i in range(10)]
    if ma_prices is None:
        ma_prices = [900.0] * 30
    return PriceSnapshot(prices, ma_prices, min_3m, min_6m)


def indicators(price: float = 900.0, **overrides) -> MarketIndicators:
    """默认是一组「有数据、无异常」的指标，便于逐个改字段做定向测试"""
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


def lot(
    grams: float,
    price: float,
    trade_date: str = "2026-01-01",
    plan_id: int | None = None,
    symbol: str = "gds_AUTD",
) -> dict:
    return {
        "id": 0,
        "symbol": symbol,
        "trade_date": trade_date,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
        "plan_id": plan_id,
    }


def plan_raw(
    plan_id: int = 1,
    target_grams: float = 100.0,
    tranches: int = 4,
    status: str = "active",
    trigger_policy: dict | None = None,
) -> dict:
    return {
        "id": plan_id,
        "symbol": "gds_AUTD",
        "target_grams": target_grams,
        "tranches": tranches,
        "status": status,
        "trigger_policy": trigger_policy or {},
        "start_date": "2026-01-01",
        "end_date": None,
    }


def make_context(
    price: float = 900.0,
    ind: MarketIndicators | None = None,
    lots: list[dict] | None = None,
    plans: list[dict] | None = None,
    prefs: AdvicePrefs | None = None,
) -> AdviceContext:
    lots = list(lots or [])
    plans = list(plans or [])
    position = compute_position("gds_AUTD", lots, latest_price=price)
    progress = summarize_plans(plans, lots)
    return AdviceContext(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        indicators=ind or indicators(price),
        position=position,
        plans=build_plan_states(plans, progress, lots, DAY),
        prefs=prefs or AdvicePrefs(),
    )


# ==================== 1. 指标提取 ====================


def test_market_indicators_from_snapshot() -> None:
    snapshot = make_snapshot(min_3m=880.0, min_6m=850.0)
    ind = MarketIndicators.from_snapshot(snapshot, 905.0)

    assert ind.count_24h == 10
    assert ind.avg_24h == 904.5
    assert ind.min_24h == 900.0
    assert ind.max_24h == 909.0
    assert ind.volatility_pct is not None and ind.volatility_pct > 0
    # (905-880)/880*100
    assert abs(ind.pct_from_3m_low - 2.8409) < 0.01
    assert abs(ind.pct_from_6m_low - 6.4706) < 0.01
    assert abs(ind.pct_from_24h_low - 0.5556) < 0.01
    assert abs(ind.range_position_24h - 0.5556) < 0.01
    assert ind.ma5 == 900.0
    assert len(ind.recent_prices) == 5


def test_market_indicators_without_snapshot() -> None:
    ind = MarketIndicators.from_snapshot(None, 900.0)
    assert ind.count_24h == 0
    assert ind.avg_24h is None
    assert ind.pct_from_3m_low is None
    # 序列化时不应出现 None 字段，避免证据里塞满空值
    payload = ind.to_dict()
    assert payload["current_price"] == 900.0
    assert "avg_24h" not in payload


# ==================== 2. 信号 ====================


def test_no_market_data_signal() -> None:
    ctx = make_context(ind=MarketIndicators(current_price=900.0))
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "no_market_data")


def test_long_term_low_signals() -> None:
    ctx = make_context(
        ind=indicators(pct_from_3m_low=0.3, min_3m=897.0, pct_from_6m_low=1.2, min_6m=889.0)
    )
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "long_term_low_3m")
    assert not signal_rules.has(found, "long_term_low_6m"), "1.2% 已超出 0.5% 容差"


def test_absolute_low_signal_preserves_legacy_safety_line() -> None:
    """原来 alert_service 里唯一活着的规则（绝对低价），现在作为信号保留"""
    below = make_context(
        price=900.0, prefs=AdvicePrefs(absolute_low_price=915.0)
    )
    found = signal_rules.evaluate(below)
    assert signal_rules.has(found, "absolute_low")
    assert signal_rules.get(found, "absolute_low").severity == "critical"

    above = make_context(price=930.0, prefs=AdvicePrefs(absolute_low_price=915.0))
    assert not signal_rules.has(signal_rules.evaluate(above), "absolute_low")

    # 未设置安全线（0）时不应触发
    unset = make_context(price=100.0, prefs=AdvicePrefs())
    assert not signal_rules.has(signal_rules.evaluate(unset), "absolute_low")


def test_absolute_low_signal_respects_enable_switch() -> None:
    """设置页把安全线关掉，它就该真的不生效（原来 enable_absolute_alert 没人读）"""
    disabled = make_context(
        price=900.0,
        prefs=AdvicePrefs(absolute_low_price=915.0, absolute_alert_enabled=False),
    )
    assert not signal_rules.has(signal_rules.evaluate(disabled), "absolute_low")

    enabled = make_context(
        price=900.0,
        prefs=AdvicePrefs(absolute_low_price=915.0, absolute_alert_enabled=True),
    )
    assert signal_rules.has(signal_rules.evaluate(enabled), "absolute_low")


def test_engine_reads_absolute_low_from_alert_config() -> None:
    with temp_db("abs.db") as db:
        engine = make_engine(db, config={})
        engine.settings.absolute_low_price = 915.0
        engine.settings.absolute_alert_enabled = False
        prefs = engine.get_prefs()
        assert prefs.absolute_low_price == 915.0
        assert prefs.absolute_alert_enabled is False


def test_range_position_signals() -> None:
    low = signal_rules.evaluate(make_context(ind=indicators(range_position_24h=0.1)))
    assert signal_rules.has(low, "near_24h_low")

    high = signal_rules.evaluate(make_context(ind=indicators(range_position_24h=0.9)))
    assert signal_rules.has(high, "near_24h_high")


def test_volatility_and_trend_signals() -> None:
    ctx = make_context(
        ind=indicators(volatility_pct=1.5, trend_24h_direction="down", ma20=1000.0)
    )
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "high_volatility")
    assert signal_rules.has(found, "trend_mid_down")
    assert signal_rules.has(found, "below_ma20")


def test_position_signals() -> None:
    no_position = signal_rules.evaluate(make_context())
    assert signal_rules.has(no_position, "no_position")

    # 浮亏 5%：900 买入，现价 855
    loss_ctx = make_context(price=855.0, lots=[lot(10, 900.0)])
    loss = signal_rules.evaluate(loss_ctx)
    assert signal_rules.has(loss, "has_position")
    assert signal_rules.has(loss, "in_loss")
    assert not signal_rules.has(loss, "deep_loss")

    # 浮亏 12%
    deep_ctx = make_context(price=792.0, lots=[lot(10, 900.0)])
    deep = signal_rules.evaluate(deep_ctx)
    assert signal_rules.has(deep, "deep_loss")

    # 浮盈 10%
    profit_ctx = make_context(price=990.0, lots=[lot(10, 900.0)])
    profit = signal_rules.evaluate(profit_ctx)
    assert signal_rules.has(profit, "big_profit")


def test_position_ratio_high_signal() -> None:
    ctx = make_context(
        price=900.0,
        lots=[lot(10, 900.0)],
        prefs=AdvicePrefs(total_investable=8000.0),
    )
    found = signal_rules.evaluate(ctx)
    # 市值 9000 / 总资金 8000 = 112.5%
    assert signal_rules.has(found, "position_ratio_high")


def test_plan_due_by_interval() -> None:
    raw = plan_raw(trigger_policy={"type": "interval", "days": 7})
    # 上次买入在 10 天前 → 到点
    due = make_context(
        plans=[raw], lots=[lot(25, 900.0, trade_date="2025-12-31", plan_id=1)]
    )
    assert signal_rules.has(signal_rules.evaluate(due), "plan_due")

    # 上次买入在 2 天前 → 未到点
    not_due = make_context(
        plans=[raw], lots=[lot(25, 900.0, trade_date="2026-01-08", plan_id=1)]
    )
    assert signal_rules.has(signal_rules.evaluate(not_due), "plan_not_due")


def test_plan_due_by_drop() -> None:
    raw = plan_raw(trigger_policy={"type": "drop_pct", "pct": 1.0})
    # 上次买在 910，现价 895 → 跌 1.65% ≥ 1% → 到点
    due = make_context(
        price=895.0,
        plans=[raw],
        lots=[lot(25, 910.0, trade_date="2026-01-05", plan_id=1)],
    )
    assert signal_rules.has(signal_rules.evaluate(due), "plan_due")

    # 现价 908 → 跌 0.22% → 未到点
    not_due = make_context(
        price=908.0,
        plans=[raw],
        lots=[lot(25, 910.0, trade_date="2026-01-05", plan_id=1)],
    )
    assert signal_rules.has(signal_rules.evaluate(not_due), "plan_not_due")


def test_plan_first_tranche_is_always_due() -> None:
    """还没买过任何一批时，视为可以开始建仓"""
    raw = plan_raw(trigger_policy={"type": "interval", "days": 30})
    ctx = make_context(plans=[raw])
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "plan_due")


def test_plan_complete_signal() -> None:
    raw = plan_raw(target_grams=25.0, tranches=1)
    ctx = make_context(plans=[raw], lots=[lot(25, 900.0, plan_id=1)])
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "plan_complete")
    assert not signal_rules.has(found, "plan_active")


def test_inactive_plan_is_logged_but_excluded() -> None:
    raw = plan_raw(status="paused", trigger_policy={"type": "interval", "days": 1})
    ctx = make_context(plans=[raw], lots=[lot(10, 900.0, plan_id=1)])
    found = signal_rules.evaluate(ctx)
    assert signal_rules.has(found, "plan_inactive")
    assert not signal_rules.has(found, "plan_due")
    assert ctx.active_plan is None


# ==================== 3. 策略调度与产出 ====================


def test_select_kind_priority() -> None:
    # 有计划 → 计划执行
    with_plan = make_context(plans=[plan_raw()])
    assert select_kind(with_plan) is AdviceKind.PLAN_EXECUTION

    # 有持仓、无计划 → 购买后
    with_position = make_context(lots=[lot(10, 900.0)])
    assert select_kind(with_position) is AdviceKind.POST_PURCHASE

    # 都没有 → 购买前
    assert select_kind(make_context()) is AdviceKind.PRE_PURCHASE


def test_plan_execution_buys_when_due() -> None:
    raw = plan_raw(target_grams=100.0, tranches=4,
                   trigger_policy={"type": "interval", "days": 7})
    ctx = make_context(
        price=900.0,
        plans=[raw],
        lots=[lot(25, 880.0, trade_date="2025-12-31", plan_id=1)],
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.kind is AdviceKind.PLAN_EXECUTION
    assert draft.action is AdviceAction.BUY_PARTIAL
    assert draft.target_grams == 25.0, "每批 = 总克数 / 批次数"
    assert draft.price_band_low is not None and draft.price_band_low < 900.0
    assert "75" in draft.rationale or "100" in draft.rationale


def test_plan_execution_waits_when_not_due() -> None:
    raw = plan_raw(trigger_policy={"type": "interval", "days": 30})
    ctx = make_context(
        plans=[raw], lots=[lot(25, 900.0, trade_date="2026-01-09", plan_id=1)]
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.WAIT
    assert draft.target_grams is None


def test_plan_execution_respects_remaining_grams() -> None:
    raw = plan_raw(target_grams=30.0, tranches=4,
                   trigger_policy={"type": "interval", "days": 1})
    ctx = make_context(
        plans=[raw], lots=[lot(25, 900.0, trade_date="2026-01-01", plan_id=1)]
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_PARTIAL
    assert draft.target_grams == 5.0, "只剩 5g，不应按每批 7.5g 建议"


def test_pre_purchase_at_long_term_low() -> None:
    ctx = make_context(
        ind=indicators(pct_from_3m_low=0.2, min_3m=898.0, trend_24h_direction="stable"),
        prefs=AdvicePrefs(target_grams=50.0),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.kind is AdviceKind.PRE_PURCHASE
    assert draft.action is AdviceAction.BUY_NOW
    assert draft.target_grams == 50.0


def test_pre_purchase_without_prefs_gives_no_grams() -> None:
    """没配目标克数/总资金时只给方向，不给数量 —— 不能凭空编一个数"""
    ctx = make_context(
        ind=indicators(pct_from_3m_low=0.2, min_3m=898.0),
        prefs=AdvicePrefs(),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_NOW
    assert draft.target_grams is None
    assert "只给方向" in draft.rationale


def test_pre_purchase_splits_when_volatile() -> None:
    ctx = make_context(
        ind=indicators(volatility_pct=2.0, range_position_24h=0.9),
        prefs=AdvicePrefs(target_grams=60.0),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_PARTIAL
    assert draft.target_grams == 20.0, "高波动时只买 1/3（60/3）"
    assert "1/3" in draft.rationale


def test_pre_purchase_avoids_chasing_rally() -> None:
    """已远离长期低点、又在区间上沿上涨 → 不建议追高"""
    ctx = make_context(
        ind=indicators(
            pct_from_6m_low=20.0,
            min_6m=750.0,
            range_position_24h=0.95,
            trend_24h_direction="up",
        ),
        prefs=AdvicePrefs(target_grams=50.0),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.kind is AdviceKind.PRE_PURCHASE
    assert draft.action is AdviceAction.AVOID
    assert draft.target_grams is None


def test_far_from_low_signal_threshold() -> None:
    near = signal_rules.evaluate(make_context(ind=indicators(pct_from_6m_low=5.0)))
    assert not signal_rules.has(near, "far_from_long_term_low")

    far = signal_rules.evaluate(make_context(ind=indicators(pct_from_6m_low=20.0)))
    assert signal_rules.has(far, "far_from_long_term_low")


def test_pre_purchase_without_prefs_still_gives_direction() -> None:
    """未配置偏好时只给方向，不给数量"""
    ctx = make_context(
        ind=indicators(pct_from_3m_low=0.2, min_3m=898.0), prefs=AdvicePrefs()
    )
    ctx_flags = ctx.prefs_configured
    assert ctx_flags is False
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_NOW
    assert draft.target_grams is None


def test_post_purchase_stop_loss() -> None:
    ctx = make_context(
        price=792.0,  # 浮亏 12%
        lots=[lot(10, 900.0)],
        ind=indicators(792.0, trend_24h_direction="down"),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.kind is AdviceKind.POST_PURCHASE
    assert draft.action is AdviceAction.STOP_LOSS
    assert draft.target_grams == 5.0, "建议减一半"


def test_post_purchase_holds_on_deep_loss_without_downtrend() -> None:
    """深亏但趋势没继续走坏时不建议割肉"""
    ctx = make_context(
        price=792.0,
        lots=[lot(10, 900.0)],
        ind=indicators(792.0, trend_24h_direction="stable"),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.HOLD


def test_post_purchase_adds_at_long_term_low() -> None:
    ctx = make_context(
        price=855.0,  # 浮亏 5%
        lots=[lot(10, 900.0)],
        ind=indicators(
            855.0, pct_from_3m_low=0.3, min_3m=852.0, trend_24h_direction="stable"
        ),
        prefs=AdvicePrefs(target_grams=30.0),
    )
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.ADD
    # 剩余目标 20g，补一半 → 10g
    assert draft.target_grams == 10.0


def test_post_purchase_takes_profit() -> None:
    ctx = make_context(price=990.0, lots=[lot(9, 900.0)])
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.TAKE_PROFIT
    assert draft.target_grams == 3.0, "止盈三分之一"


def test_post_purchase_holds_when_flat() -> None:
    ctx = make_context(price=901.0, lots=[lot(10, 900.0)])
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.HOLD
    assert "成本价" in draft.rationale


def test_no_market_data_yields_wait_or_hold() -> None:
    pre = make_context(ind=MarketIndicators(current_price=900.0))
    assert build_advice(pre, signal_rules.evaluate(pre)).action is AdviceAction.WAIT

    post = make_context(
        lots=[lot(10, 900.0)], ind=MarketIndicators(current_price=900.0)
    )
    assert build_advice(post, signal_rules.evaluate(post)).action is AdviceAction.HOLD


def test_draft_evidence_is_frozen() -> None:
    ctx = make_context(price=900.0, lots=[lot(10, 880.0)], prefs=AdvicePrefs(target_grams=20.0))
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    evidence = draft.evidence
    assert evidence["market"]["current_price"] == 900.0
    assert evidence["position"]["avg_cost"] == 880.0
    assert evidence["position"]["unrealized_pnl"] == 200.0
    assert "advised_at" in evidence


# ==================== 4. 持久化 ====================


def test_advice_mapper_roundtrip() -> None:
    with temp_db("advice.db") as db:
        mapper = AdviceMapper(db_file=db)
        assert mapper.list_advice() == []

        advice_id = mapper.insert_advice(
            {
                "kind": "pre_purchase",
                "action": "BUY_NOW",
                "symbol": "gds_AUTD",
                "target_grams": 25.0,
                "confidence": 0.7,
                "rationale": "测试理由",
                "signals": [{"id": "long_term_low_3m", "category": "market",
                             "severity": "notice", "summary": "贴近低点", "metrics": {}}],
                "evidence": {"market": {"current_price": 900.0}},
                "model_info": "p/m",
                "price_at_advice": 900.0,
            }
        )
        assert advice_id > 0

        stored = mapper.get_advice(advice_id)
        assert stored is not None
        assert stored["action"] == "BUY_NOW"
        assert stored["target_grams"] == 25.0
        assert stored["signals"][0]["id"] == "long_term_low_3m", "signals 应还原成对象"
        assert stored["evidence"]["market"]["current_price"] == 900.0
        assert stored["status"] == "delivered", "未传 status 应走 DDL 默认值"
        assert stored["created_at"]


def test_advice_mapper_defaults_are_not_null() -> None:
    """只给必填字段也应能写入（DEFAULT 生效，不撞 NOT NULL）"""
    with temp_db("defaults.db") as db:
        mapper = AdviceMapper(db_file=db)
        advice_id = mapper.insert_advice(
            {"kind": "review", "action": "HOLD", "symbol": "gds_AUTD"}
        )
        stored = mapper.get_advice(advice_id)
        assert stored["rationale"] == ""
        assert stored["signals"] == []
        assert stored["evidence"] == {}
        assert stored["confidence"] == 0.5
        assert stored["suppressed_reason"] == ""


def test_advice_mapper_status_and_filters() -> None:
    with temp_db("status.db") as db:
        mapper = AdviceMapper(db_file=db)
        first = mapper.insert_advice(
            {"kind": "pre_purchase", "action": "WAIT", "symbol": "gds_AUTD"}
        )
        mapper.insert_advice(
            {"kind": "post_purchase", "action": "HOLD", "symbol": "hf_XAU"}
        )

        assert mapper.update_status(first, "acknowledged") is True
        assert mapper.get_advice(first)["status"] == AdviceStatus.ACKNOWLEDGED.value
        assert mapper.update_status(9999, "acted") is False

        assert mapper.count_advice() == 2
        assert mapper.count_advice(symbol="gds_AUTD") == 1
        assert mapper.count_advice(kind="post_purchase") == 1
        assert len(mapper.list_advice(status="acknowledged")) == 1
        # 最新的排在前面
        assert mapper.list_advice()[0]["symbol"] == "hf_XAU"


def test_advice_mapper_review_tracking() -> None:
    with temp_db("review.db") as db:
        mapper = AdviceMapper(db_file=db)
        old = (now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        advice_id = mapper.insert_advice(
            {
                "kind": "pre_purchase",
                "action": "BUY_NOW",
                "symbol": "gds_AUTD",
                "price_at_advice": 900.0,
                "created_at": old,
            }
        )
        # T+30 还没到期
        assert mapper.list_pending_reviews(30) == []
        pending = mapper.list_pending_reviews(1)
        assert [item["id"] for item in pending] == [advice_id]

        assert mapper.update_review_prices(advice_id, "price_t1", 918.0) is True
        assert mapper.list_pending_reviews(1) == [], "回填后不应再出现"
        assert mapper.update_review_prices(advice_id, "price_t1", 999.0) is False, (
            "已有值不应被覆盖"
        )

        assert mapper.get_advice(advice_id)["price_t1"] == 918.0
        assert mapper.get_advice(advice_id)["reviewed_at"]

        stats = mapper.review_stats()
        assert stats["total"] == 1
        assert stats["with_t1"] == 1
        assert abs(stats["avg_move_t1_pct"] - 2.0) < 0.01
        assert stats["with_t7"] == 0


def test_advice_mapper_rejects_bad_horizon() -> None:
    with temp_db("horizon.db") as db:
        mapper = AdviceMapper(db_file=db)
        with assert_raises(ValueError, match="回访档位"):
            mapper.list_pending_reviews(5)
        with assert_raises(ValueError, match="回访档位"):
            mapper.update_review_prices(1, "price_t5", 1.0)


def test_advice_mapper_degrades_on_bad_json() -> None:
    with temp_db("badjson.db") as db:
        mapper = AdviceMapper(db_file=db)
        advice_id = mapper.insert_advice(
            {"kind": "review", "action": "HOLD", "symbol": "gds_AUTD"}
        )
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE advice_records SET signals = ?, evidence = ? WHERE id = ?",
            ("{not json", "[not json", advice_id),
        )
        conn.commit()
        conn.close()

        stored = mapper.get_advice(advice_id)
        assert stored["signals"] == []
        assert stored["evidence"] == {}


# ==================== 5. 引擎编排 ====================


class FakePriceMapper:
    def __init__(self, snapshot=None, latest=None, near=None):
        self.snapshot = snapshot
        self.latest = latest
        self.near = near
        self.near_calls: list[tuple[str, int]] = []

    def get_check_snapshot(self, symbol):
        return self.snapshot

    def get_latest_price(self, symbol):
        return self.latest

    def get_price_near(self, symbol, timestamp):
        self.near_calls.append((symbol, timestamp))
        return self.near if self.near is not None else self.latest


class FakePortfolioMapper:
    def __init__(self, lots, plans):
        self.lots = list(lots)
        self.plans = list(plans)

    def list_lots(self, symbol=None):
        return [row for row in self.lots if symbol is None or row["symbol"] == symbol]

    def list_plans(self, symbol=None, status=None):
        return [row for row in self.plans if symbol is None or row["symbol"] == symbol]


class FakeSettings:
    def __init__(
        self,
        config: dict | None = None,
        main_symbol: str = "gds_AUTD",
        absolute_low_price: float = 0.0,
        absolute_alert_enabled: bool = True,
    ):
        self.config = config or {}
        self.main_symbol = main_symbol
        self.absolute_low_price = absolute_low_price
        self.absolute_alert_enabled = absolute_alert_enabled

    def get_advice_config(self):
        return self.config

    def get_alert_config(self):
        return {
            "absolute_low_price": self.absolute_low_price,
            "enable_absolute_alert": self.absolute_alert_enabled,
        }

    def get_monitor_config(self):
        return {"main_symbol": self.main_symbol}

    def get_symbol_name_map(self):
        return {"gds_AUTD": "黄金T+D"}


class FakeAdvisor:
    def __init__(self, text: str | None = None, model_info: str = "fake/model"):
        self.text = text
        self.model_info = model_info
        self.calls = 0

    def phrase(self, ctx, draft):
        self.calls += 1
        return (self.text if self.text is not None else draft.rationale), self.model_info


class FakeEntryEvaluator:
    """默认返回 None，等价于「历史数据不足」，让策略走经验兜底分支"""

    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    def evaluate(self, symbol, current_price, **kwargs):
        self.calls += 1
        return self.result


def make_engine(
    db: str,
    snapshot=None,
    lots=(),
    plans=(),
    config: dict | None = None,
    advisor=None,
    entry_result=None,
) -> AdviceEngine:
    engine = object.__new__(AdviceEngine)
    engine.settings = FakeSettings(config)
    engine.price_mapper = FakePriceMapper(snapshot)
    engine.portfolio_mapper = FakePortfolioMapper(list(lots), list(plans))
    engine.advice_mapper = AdviceMapper(db_file=db)
    engine.advisor = advisor or FakeAdvisor()
    engine.entry_evaluator = FakeEntryEvaluator(entry_result)
    return engine


def test_engine_generates_and_persists() -> None:
    with temp_db("engine.db") as db:
        engine = make_engine(
            db,
            snapshot=make_snapshot(min_3m=898.0),
            config={"target_grams": 50.0, "enable_llm": False},
        )
        record = engine.generate("gds_AUTD", 900.0, use_llm=False)

        assert record.id > 0
        assert record.kind is AdviceKind.PRE_PURCHASE
        assert record.action is AdviceAction.BUY_NOW
        assert record.target_grams == 50.0
        assert record.price_at_advice == 900.0
        assert record.model_info == "", "跳过 LLM 时不应有模型信息"
        assert record.signals, "应记录命中的信号"
        assert record.evidence["market"]["current_price"] == 900.0

        # 确实落库了
        assert engine.count() == 1
        assert engine.get(record.id).action is AdviceAction.BUY_NOW


def test_engine_uses_advisor_when_enabled() -> None:
    with temp_db("llm.db") as db:
        advisor = FakeAdvisor(text="AI 改写后的理由", model_info="p/m")
        engine = make_engine(
            db, snapshot=make_snapshot(min_3m=898.0), config={"enable_llm": True},
            advisor=advisor,
        )
        record = engine.generate("gds_AUTD", 900.0)

        assert advisor.calls == 1
        assert record.rationale == "AI 改写后的理由"
        assert record.model_info == "p/m"
        # 关键：模型只改措辞，结论与数字不变
        assert record.action is AdviceAction.BUY_NOW


def test_engine_falls_back_to_rule_rationale() -> None:
    with temp_db("fallback.db") as db:
        class FailingAdvisor:
            def phrase(self, ctx, draft):
                return draft.rationale, ""

        engine = make_engine(
            db, snapshot=make_snapshot(min_3m=898.0),
            config={"enable_llm": True}, advisor=FailingAdvisor(),
        )
        record = engine.generate("gds_AUTD", 900.0)
        assert record.model_info == ""
        assert record.action is AdviceAction.BUY_NOW
        assert "贴近长期低点" in record.rationale or "现价" in record.rationale


def test_engine_without_persist() -> None:
    with temp_db("preview.db") as db:
        engine = make_engine(db, snapshot=make_snapshot(min_3m=898.0),
                             config={"enable_llm": False})
        record = engine.generate("gds_AUTD", 900.0, persist=False, use_llm=False)
        assert record.id == 0
        assert engine.count() == 0, "预览不应落库"


def test_engine_lifecycle() -> None:
    with temp_db("lifecycle.db") as db:
        engine = make_engine(db, snapshot=make_snapshot(min_3m=898.0),
                             config={"enable_llm": False})
        record = engine.generate("gds_AUTD", 900.0, use_llm=False)

        assert engine.mark_acknowledged(record.id) is True
        assert engine.get(record.id).status is AdviceStatus.ACKNOWLEDGED
        assert engine.mark_acted(record.id, lot_id=7) is True
        acted = engine.get(record.id)
        assert acted.status is AdviceStatus.ACTED
        assert acted.acted_lot_id == 7

        assert engine.mark_acknowledged(9999) is False
        assert engine.get(9999) is None


def test_engine_history_pagination() -> None:
    with temp_db("history.db") as db:
        engine = make_engine(db, snapshot=make_snapshot(min_3m=898.0),
                             config={"enable_llm": False})
        for _ in range(5):
            engine.generate("gds_AUTD", 900.0, use_llm=False)

        assert engine.count() == 5
        assert len(engine.history(limit=2)) == 2
        assert len(engine.history(limit=2, offset=4)) == 1
        assert engine.count(kind="pre_purchase") == 5
        assert engine.count(kind="post_purchase") == 0


def test_engine_refresh_reviews() -> None:
    with temp_db("refresh.db") as db:
        mapper = AdviceMapper(db_file=db)
        old = (now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        mapper.insert_advice(
            {
                "kind": "pre_purchase",
                "action": "BUY_NOW",
                "symbol": "gds_AUTD",
                "price_at_advice": 900.0,
                "created_at": old,
            }
        )
        engine = make_engine(db, snapshot=make_snapshot(min_3m=898.0))
        engine.price_mapper.near = 918.0

        result = engine.refresh_reviews()
        assert result["filled"] == 1
        assert result["skipped"] == 0
        assert engine.review_stats().with_t1 == 1
        # 取价用的是「目标时点」，而不是最新价
        assert engine.price_mapper.near_calls, "应通过 get_price_near 取目标时点的价格"
        symbol, target_ts = engine.price_mapper.near_calls[0]
        assert symbol == "gds_AUTD"
        assert target_ts > 0
        # 幂等：再跑一次没有新的可填
        assert engine.refresh_reviews()["filled"] == 0


def test_engine_review_stats_empty() -> None:
    with temp_db("stats.db") as db:
        engine = make_engine(db)
        stats = engine.review_stats()
        assert stats.total == 0
        assert stats.avg_move_t1_pct is None


def test_engine_prefs_configured_flag() -> None:
    with temp_db("prefs.db") as db:
        configured = make_engine(db, config={"target_grams": 50.0})
        ctx = configured.build_context("gds_AUTD", 900.0)
        assert ctx.prefs_configured is True

        empty = make_engine(db, config={})
        assert empty.build_context("gds_AUTD", 900.0).prefs_configured is False


def test_engine_planned_kind() -> None:
    with temp_db("kind.db") as db:
        engine = make_engine(db, plans=[plan_raw()])
        assert engine.planned_kind("gds_AUTD", 900.0) is AdviceKind.PLAN_EXECUTION


# ==================== 6. 计划状态 ====================


def test_plan_state_next_tranche_grams() -> None:
    raw = plan_raw(target_grams=100.0, tranches=4)
    states = build_plan_states(
        [raw], summarize_plans([raw], []), [], DAY
    )
    assert states[0].next_tranche_grams() == 25.0

    filled = [lot(90, 900.0, plan_id=1)]
    states = build_plan_states([raw], summarize_plans([raw], filled), filled, DAY)
    assert states[0].next_tranche_grams() == 10.0, "剩余不足一批时按剩余给"


def test_plan_state_days_since_last_lot() -> None:
    raw = plan_raw()
    lots = [lot(10, 900.0, trade_date="2026-01-03", plan_id=1)]
    states = build_plan_states([raw], summarize_plans([raw], lots), lots, DAY)
    assert states[0].days_since_last_lot == 7
    assert states[0].last_lot_price == 900.0


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
