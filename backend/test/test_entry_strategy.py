"""建仓方式评估测试（阶段 3）。

覆盖：
- 纯计算：滚动波动率、分位、三种建仓方式的每克平均成本（含手工可验算的用例）
- 回测与推荐：上升行情不该分批、下跌行情该分批、样本不足要诚实说不知道
- 与建议流程的衔接：`pre_purchase` 用回测结论决定「一次买满还是分几批」
- 序列缓存的命中与失效

运行
----
    cd backend
    python -m test.test_entry_strategy
"""

import contextlib
import random
from datetime import date, timedelta

from models.advice import AdviceAction, AdviceKind, AdvicePrefs
from service.advice import signals as signal_rules
from service.advice.context import AdviceContext, MarketIndicators, build_plan_states
from service.advice.entry_strategy import (
    DROP_TRIGGER_PCT,
    MIN_SAMPLES,
    SPLIT_WORST_CASE_CAP_PCT,
    EntryStrategyEvaluator,
    evaluate_entry_strategy,
    percentile_rank,
    rolling_volatility,
    simulate_avg_cost,
)
from service.advice.strategies import build_advice
from service.position import compute_position, summarize_plans

START = date(2025, 1, 1)


@contextlib.contextmanager
def assert_raises(exc_type: type[BaseException], match: str | None = None):
    try:
        yield
    except exc_type as exc:
        if match is not None and match not in str(exc):
            raise AssertionError(f"异常信息中不含 {match!r}：{exc}") from exc
    else:
        raise AssertionError(f"未按预期抛出 {exc_type.__name__}")


def make_series(prices: list[float]) -> list[tuple[date, float]]:
    return [(START + timedelta(days=i), price) for i, price in enumerate(prices)]


def walk(
    length: int, start: float = 900.0, drift: float = 0.0, vol: float = 0.01, seed: int = 42
) -> list[float]:
    """确定性的随机游走，用于构造可复现的历史序列"""
    rnd = random.Random(seed)
    prices = [start]
    for _ in range(length - 1):
        prices.append(prices[-1] * (1 + drift + rnd.gauss(0, vol)))
    return prices


# ==================== 1. 纯计算 ====================


def test_rolling_volatility_flat_series_is_zero() -> None:
    vols = rolling_volatility([900.0] * 40, window=20)
    assert len(vols) == 40
    assert all(value == 0.0 for value in vols), "价格不变时波动率应为 0"


def test_rolling_volatility_detects_swings() -> None:
    calm = rolling_volatility([900.0, 901.0] * 20, window=10)
    wild = rolling_volatility([900.0, 930.0] * 20, window=10)
    assert wild[-1] > calm[-1] > 0
    # 前 window 个位置没有足够样本，填 0
    assert all(value == 0.0 for value in calm[:10])


def test_percentile_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_rank(values, 5.0) == 100.0
    assert percentile_rank(values, 3.0) == 60.0
    assert percentile_rank(values, 0.5) == 0.0
    assert percentile_rank(values, 0.0) is None
    assert percentile_rank([], 1.0) is None


def test_simulate_lump_sum_is_first_price() -> None:
    window = [100.0, 110.0, 120.0, 130.0, 140.0]
    assert simulate_avg_cost(window, "lump_sum", 1, 4) == 100.0
    # tranches <= 1 也按一次性处理
    assert simulate_avg_cost(window, "interval", 1, 4) == 100.0


def test_simulate_interval_hand_computed() -> None:
    """window=[100,110,120,130,140]，horizon=4，分 2 批 → 第 0、2 天买入 → 均价 110"""
    window = [100.0, 110.0, 120.0, 130.0, 140.0]
    assert simulate_avg_cost(window, "interval", 2, 4) == 110.0


def test_simulate_interval_rising_vs_falling() -> None:
    rising = [100.0, 105.0, 110.0, 115.0, 120.0]
    falling = [120.0, 115.0, 110.0, 105.0, 100.0]
    # 上涨时分批买在更高的位置
    assert simulate_avg_cost(rising, "interval", 2, 4) > rising[0]
    # 下跌时分批买在更低的位置
    assert simulate_avg_cost(falling, "interval", 2, 4) < falling[0]


def test_simulate_drop_pct_triggers_on_drop() -> None:
    """跌 1% 即补一批：[100,99,98,97,96] 第 1 天就触发 → 均价 99.5"""
    window = [100.0, 99.0, 98.0, 97.0, 96.0]
    assert simulate_avg_cost(window, "drop_pct", 2, 4) == 99.5


def test_simulate_drop_pct_fills_remainder_at_end() -> None:
    """一路上涨从不触发 → 期末按最后一天价补足，保证与一次性可比"""
    window = [100.0, 101.0, 102.0, 103.0, 104.0]
    assert simulate_avg_cost(window, "drop_pct", 2, 4) == 102.0


def test_simulate_drop_pct_never_exceeds_window() -> None:
    window = [100.0, 96.0, 92.0, 88.0, 84.0]
    avg = simulate_avg_cost(window, "drop_pct", 5, 4)
    assert min(window) <= avg <= max(window)


def test_drop_trigger_threshold_is_one_percent() -> None:
    # 恰好跌 1% 应触发（<= 比较）
    window = [100.0, 99.0, 99.0, 99.0, 99.0]
    assert simulate_avg_cost(window, "drop_pct", 2, 4) == 99.5
    assert DROP_TRIGGER_PCT == 1.0


# ==================== 2. 回测与推荐 ====================


def test_insufficient_data_is_honest() -> None:
    """数据不足时要明确说不知道，而不是用几个样本编结论"""
    result = evaluate_entry_strategy("gds_AUTD", make_series([900.0] * 40), 900.0)
    assert result.sufficient_data is False
    assert result.recommended_tranches == 1
    assert result.outcomes == []
    assert "历史数据不足" in result.explanation


def test_falling_market_favours_splitting() -> None:
    prices = walk(220, start=1000.0, drift=-0.003, vol=0.006, seed=7)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    assert result.sufficient_data is True
    assert result.sample_count >= MIN_SAMPLES
    assert result.recommended_tranches > 1, "持续下跌时分批应更划算"
    assert result.recommended is not None
    assert result.recommended.avg_cost_diff_pct < 0
    assert "分批" in result.explanation
    assert "跑赢一次性的概率" in result.explanation


def test_rising_market_favours_lump_sum() -> None:
    prices = walk(220, start=900.0, drift=0.002, vol=0.006, seed=11)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    assert result.sufficient_data is True
    assert result.recommended_tranches == 1, "持续上涨时分批只会买得更贵"
    assert result.recommended is not None
    assert result.recommended.method == "lump_sum"
    assert "建议一次性买入" in result.explanation
    assert "高" in result.explanation, "应说明分批更贵"


def test_baseline_is_included_in_outcomes() -> None:
    prices = walk(220, start=900.0, drift=-0.001, vol=0.01, seed=3)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    methods = {outcome.method for outcome in result.outcomes}
    assert "lump_sum" in methods, "一次性必须作为对照出现在结果里"
    assert "interval" in methods and "drop_pct" in methods
    baseline = next(o for o in result.outcomes if o.method == "lump_sum")
    assert baseline.avg_cost_diff_pct == 0.0
    assert baseline.worst_case_pct == 0.0


def test_outcomes_are_sorted_by_avg_cost() -> None:
    prices = walk(220, start=900.0, drift=-0.001, vol=0.012, seed=5)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    averages = [outcome.avg_cost_diff_pct for outcome in result.outcomes]
    assert averages == sorted(averages)


def test_worst_case_tolerance_is_adaptive() -> None:
    """容忍度随「一次性买入价本身的离散度」走，并有上下限"""
    calm = walk(220, start=900.0, drift=0.0, vol=0.002, seed=2)
    wild = walk(220, start=900.0, drift=0.0, vol=0.02, seed=2)
    calm_result = evaluate_entry_strategy("gds_AUTD", make_series(calm), calm[-1])
    wild_result = evaluate_entry_strategy("gds_AUTD", make_series(wild), wild[-1])

    assert calm_result.worst_case_tolerance_pct is not None
    assert wild_result.worst_case_tolerance_pct is not None
    assert (
        calm_result.worst_case_tolerance_pct
        <= wild_result.worst_case_tolerance_pct
    ), "行情越颠簸，容忍度应越宽"
    assert wild_result.worst_case_tolerance_pct <= SPLIT_WORST_CASE_CAP_PCT
    assert wild_result.lump_dispersion_pct is not None


def test_recommendation_respects_worst_case_filter() -> None:
    """被推荐的分批方案必须既更便宜、又在容忍度内"""
    prices = walk(220, start=900.0, drift=-0.002, vol=0.02, seed=13)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    if result.recommended and result.recommended.method != "lump_sum":
        assert result.recommended.avg_cost_diff_pct < 0
        assert result.recommended.worst_case_pct <= (result.worst_case_tolerance_pct or 0)


def test_evaluation_is_deterministic() -> None:
    prices = walk(200, start=900.0, drift=-0.0008, vol=0.011, seed=17)
    series = make_series(prices)
    first = evaluate_entry_strategy("gds_AUTD", series, prices[-1])
    second = evaluate_entry_strategy("gds_AUTD", series, prices[-1])
    assert first.recommended_tranches == second.recommended_tranches
    assert first.sample_count == second.sample_count
    assert first.explanation == second.explanation


def test_volatility_percentile_is_reported() -> None:
    prices = walk(220, start=900.0, drift=0.0, vol=0.012, seed=19)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    assert result.volatility_pct is not None and result.volatility_pct > 0
    assert result.volatility_percentile is not None
    assert 0 <= result.volatility_percentile <= 100


def test_result_serialises() -> None:
    prices = walk(220, start=900.0, drift=-0.001, vol=0.01, seed=23)
    payload = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1]).to_dict()
    assert payload["symbol"] == "gds_AUTD"
    assert isinstance(payload["outcomes"], list)
    assert payload["recommended_tranches"] >= 1
    assert "explanation" in payload


def test_series_with_zero_prices_is_filtered() -> None:
    prices = walk(220, start=900.0, drift=-0.001, vol=0.01, seed=29)
    series = make_series(prices)
    series[5] = (series[5][0], 0.0)
    result = evaluate_entry_strategy("gds_AUTD", series, prices[-1])
    assert result.series_points == len(series) - 1


# ==================== 3. 序列缓存 ====================


class CountingPriceMapper:
    def __init__(self, series):
        self.series = series
        self.calls = 0

    def get_chart_series(self, symbol, hours=None, start_date=None, end_date=None):
        self.calls += 1
        return self.series


def test_series_cache_hits_and_invalidates() -> None:
    from datetime import datetime

    prices = walk(220, start=900.0, drift=-0.001, vol=0.01, seed=31)
    rows = [
        (datetime.combine(day, datetime.min.time()), price)
        for day, price in make_series(prices)
    ]
    mapper = CountingPriceMapper(rows)
    evaluator = EntryStrategyEvaluator(mapper, series_ttl_seconds=3600)

    evaluator.evaluate("gds_AUTD", prices[-1])
    evaluator.evaluate("gds_AUTD", prices[-1])
    assert mapper.calls == 1, "同一天内不应重复聚合历史序列"

    evaluator.invalidate_cache()
    evaluator.evaluate("gds_AUTD", prices[-1])
    assert mapper.calls == 2


def test_series_cache_expires() -> None:
    from datetime import datetime

    prices = walk(120, start=900.0, drift=0.0, vol=0.01, seed=37)
    rows = [
        (datetime.combine(day, datetime.min.time()), price)
        for day, price in make_series(prices)
    ]
    mapper = CountingPriceMapper(rows)
    evaluator = EntryStrategyEvaluator(mapper, series_ttl_seconds=0)
    evaluator.evaluate("gds_AUTD", prices[-1])
    evaluator.evaluate("gds_AUTD", prices[-1])
    assert mapper.calls == 2, "TTL 为 0 时每次都重新取"


# ==================== 4. 与建议流程的衔接 ====================


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


def make_context(
    price: float = 900.0,
    ind: MarketIndicators | None = None,
    prefs: AdvicePrefs | None = None,
    entry_strategy=None,
) -> AdviceContext:
    return AdviceContext(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        indicators=ind or indicators(price),
        position=compute_position("gds_AUTD", [], latest_price=price),
        plans=build_plan_states([], summarize_plans([], []), [], date(2026, 1, 10)),
        prefs=prefs or AdvicePrefs(target_grams=60.0),
        entry_strategy=entry_strategy,
    )


def test_pre_purchase_uses_backtest_to_split() -> None:
    """回测建议分批 → 建议动作是分批，且先买 1/N"""
    prices = walk(220, start=1000.0, drift=-0.003, vol=0.006, seed=41)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    assert result.recommended_tranches > 1, "前提：这段历史应当支持分批"

    ctx = make_context(price=900.0, entry_strategy=result)
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.kind is AdviceKind.PRE_PURCHASE
    assert draft.action is AdviceAction.BUY_PARTIAL
    expected = round(60.0 / result.recommended_tranches, 4)
    assert draft.target_grams == expected, f"应先买 1/{result.recommended_tranches}"
    assert "跑赢一次性" in draft.rationale or "分批" in draft.rationale


def test_pre_purchase_uses_backtest_to_buy_in_full() -> None:
    prices = walk(220, start=900.0, drift=0.002, vol=0.006, seed=43)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    assert result.recommended_tranches == 1, "前提：这段历史应支持一次性"

    ctx = make_context(price=900.0, entry_strategy=result)
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_NOW
    assert draft.target_grams == 60.0
    assert "一次性买入" in draft.rationale


def test_pre_purchase_falls_back_to_heuristic_without_backtest() -> None:
    """没有回测结论时退回经验规则：波动偏高 → 分 3 批"""
    ctx = make_context(ind=indicators(volatility_pct=2.0), entry_strategy=None)
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_PARTIAL
    assert draft.target_grams == round(60.0 / 3, 4)
    assert "历史数据不足" in draft.rationale


def test_pre_purchase_heuristic_gives_full_buy_when_calm() -> None:
    ctx = make_context(ind=indicators(), entry_strategy=None)
    draft = build_advice(ctx, signal_rules.evaluate(ctx))
    assert draft.action is AdviceAction.BUY_NOW
    assert draft.target_grams == 60.0


def test_evidence_freezes_entry_strategy() -> None:
    prices = walk(220, start=1000.0, drift=-0.003, vol=0.006, seed=47)
    result = evaluate_entry_strategy("gds_AUTD", make_series(prices), prices[-1])
    ctx = make_context(entry_strategy=result)
    evidence = ctx.to_evidence()
    assert evidence["entry_strategy"] is not None
    assert evidence["entry_strategy"]["sample_count"] == result.sample_count
    assert evidence["entry_strategy"]["recommended_tranches"] == result.recommended_tranches
    assert evidence["entry_strategy"]["explanation"]


def test_evidence_without_entry_strategy() -> None:
    evidence = make_context().to_evidence()
    assert evidence["entry_strategy"] is None


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
