"""LLM 提示词测试。

措辞层是「LLM 只能改说法、不能改结论」这道约束的落点，提示词写错了不会被任何断言
发现 —— 它只会让模型输出得更差或编造数字。这里把几条硬要求固定下来：

- 提示词必须带**建议类型**，否则复盘会被改写成一条全新的买卖建议
- 必须带**已实现盈亏**，否则模型不知道用户已经止盈过
- 必须带**风险偏好档位**，否则它解释不清为什么 +5% 就提示止盈
- 拿不到行情的字段要标明「无行情」，**不能退化成 0**
- 长度上限必须容得下规则理由（含建仓回测的那条最长）

运行
----
    cd backend
    python -m test.test_advice_prompt
"""

import contextlib
import random
from datetime import date, timedelta
from pathlib import Path

from models.advice import AdviceKind, AdvicePrefs
from service.advice import signals as signal_rules
from service.advice.advisor import RATIONALE_MAX_CHARS, AdviceAdvisor
from service.advice.context import AdviceContext, MarketIndicators, build_plan_states
from service.advice.entry_strategy import evaluate_entry_strategy
from service.advice.strategies import build_advice
from service.position import compute_position, summarize_plans


@contextlib.contextmanager
def assert_raises(exc_type: type[BaseException], match: str | None = None):
    try:
        yield
    except exc_type as exc:
        if match is not None and str(match) not in str(exc):
            raise AssertionError(f"异常信息中不含 {match!r}：{exc}") from exc
    else:
        raise AssertionError(f"未按预期抛出 {exc_type.__name__}")


def indicators(price: float, **overrides) -> MarketIndicators:
    base = {
        "current_price": price,
        "avg_24h": price,
        "max_24h": price * 1.005,
        "min_24h": price * 0.995,
        "std_24h": price * 0.001,
        "count_24h": 100,
        "volatility_pct": 0.1,
        "trend_6h_direction": "stable",
        "trend_24h_direction": "stable",
    }
    base.update(overrides)
    return MarketIndicators(**base)


def lot(grams, price, trade="2026-01-01", lot_id=1, is_opening=0):
    return {
        "id": lot_id,
        "symbol": "gds_AUTD",
        "trade_date": trade,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
        "channel": "",
        "plan_id": None,
        "is_opening": is_opening,
    }


def sale(grams, price, sale_id=1, when="2026-02-01"):
    return {
        "id": sale_id,
        "symbol": "gds_AUTD",
        "sale_date": when,
        "grams": grams,
        "price_per_gram": price,
        "fee": 0.0,
    }


def make_ctx(
    price,
    lots=(),
    sales=(),
    prefs=None,
    subject=None,
    horizon=None,
    indicators_override=None,
) -> AdviceContext:
    return AdviceContext(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        indicators=indicators_override or indicators(price),
        position=compute_position("gds_AUTD", list(lots), price, sales=list(sales)),
        plans=build_plan_states([], summarize_plans([], []), [], date(2026, 1, 10)),
        prefs=prefs or AdvicePrefs(),
        subject_lot=subject,
        review_horizon=horizon,
    )


def draft_for(ctx: AdviceContext):
    return build_advice(ctx, signal_rules.evaluate(ctx))


def prompt_for(ctx: AdviceContext) -> str:
    return AdviceAdvisor._build_prompt(ctx, draft_for(ctx))


# ==================== 1. 建议类型 ====================


def test_prompt_states_the_kind() -> None:
    """不带 kind，复盘会被改写成一条全新的买卖建议"""
    subject = lot(10.0, 900.0, trade="2026-01-13")
    ctx = make_ctx(855.0, lots=[subject], subject=subject, horizon=7)
    draft = draft_for(ctx)
    assert draft.kind is AdviceKind.REVIEW

    prompt = AdviceAdvisor._build_prompt(ctx, draft)
    assert "建议类型：review" in prompt
    assert "复盘" in prompt, "要给出「保留回访定位」的写作要求"
    assert "回访你在" in prompt, "要把「哪一笔买入」的指代交给模型"


def test_every_kind_has_guidance() -> None:
    for kind in AdviceKind:
        assert kind in AdviceAdvisor.KIND_GUIDANCE, f"{kind} 缺少写作要求"


def test_pre_purchase_prompt_has_kind_and_guidance() -> None:
    ctx = make_ctx(900.0, prefs=AdvicePrefs(target_grams=60.0))
    prompt = prompt_for(ctx)
    assert "建议类型：pre_purchase" in prompt
    assert "买入建议" in prompt


# ==================== 2. 已实现盈亏 ====================


def test_prompt_includes_realized_pnl_when_sold() -> None:
    lots = [lot(30.0, 900.0, is_opening=1)]
    sales = [sale(10.0, 1000.0)]
    ctx = make_ctx(990.0, lots=lots, sales=sales, prefs=AdvicePrefs(risk_level="conservative"))
    prompt = prompt_for(ctx)

    assert "已卖出 10.0g" in prompt
    assert "已实现盈亏 ¥1000.00" in prompt
    assert "不含手续费" in prompt


def test_prompt_omits_realized_pnl_when_never_sold() -> None:
    ctx = make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)])
    prompt = prompt_for(ctx)
    assert "已实现盈亏" not in prompt


def test_prompt_shows_cleared_position() -> None:
    """清仓后仍要告诉模型已实现盈亏，而不是简单说「没有持仓」"""
    lots = [lot(10.0, 900.0, is_opening=1)]
    sales = [sale(10.0, 1000.0)]
    ctx = make_ctx(1000.0, lots=lots, sales=sales)
    prompt = prompt_for(ctx)
    assert "当前已清仓" in prompt
    assert "已实现盈亏 ¥1000.00" in prompt


# ==================== 3. 风险偏好 ====================


def test_prompt_includes_risk_profile() -> None:
    ctx = make_ctx(990.0, lots=[lot(25.0, 900.0, is_opening=1)],
                   prefs=AdvicePrefs(risk_level="conservative"))
    prompt = prompt_for(ctx)
    assert "【风险偏好】" in prompt
    assert "档位：保守" in prompt
    assert "止损 -6%" in prompt, "要写清该档位具体阈值"


def test_risk_thresholds_follow_the_profile() -> None:
    aggressive = prompt_for(
        make_ctx(990.0, lots=[lot(25.0, 900.0, is_opening=1)],
                 prefs=AdvicePrefs(risk_level="aggressive"))
    )
    assert "档位：进取" in aggressive
    assert "止损 -15%" in aggressive


# ==================== 4. 缺失行情不能退化成 0 ====================


def test_missing_quote_is_labelled_not_zero() -> None:
    """没有浮动盈亏时应标「无行情」。

    旧实现写的是 `position.unrealized_pnl or 0`，会把「不知道」变成「持平 0%」，
    而提示词又要求模型「必须提及关键数字」—— 等于让模型复述一个假数字。
    """
    ctx = make_ctx(900.0, lots=[lot(10.0, 900.0, is_opening=1)])
    object.__setattr__(ctx.position, "unrealized_pnl", None)
    object.__setattr__(ctx.position, "unrealized_pnl_pct", None)

    prompt = AdviceAdvisor._build_prompt(ctx, draft_for(ctx))
    assert "无行情" in prompt
    assert "¥0.00" not in prompt, "不能把缺失的盈亏写成 0"
    assert "+0.00%" not in prompt


def test_system_prompt_forbids_guessing_missing_values() -> None:
    assert "无行情" in AdviceAdvisor.SYSTEM_PROMPT
    assert "不要猜测" in AdviceAdvisor.SYSTEM_PROMPT


# ==================== 5. 长度预算 ====================


def long_backtest_rationale() -> str:
    """构造最长的规则理由：购买前 + 建仓回测"""
    rnd = random.Random(7)
    prices = [1000.0]
    for _ in range(219):
        prices.append(prices[-1] * (1 - 0.003 + rnd.gauss(0, 0.006)))
    series = [(date(2025, 1, 1) + timedelta(days=i), p) for i, p in enumerate(prices)]
    backtest = evaluate_entry_strategy("gds_AUTD", series, prices[-1])

    ctx = make_ctx(900.0, prefs=AdvicePrefs(target_grams=60.0))
    ctx.entry_strategy = backtest
    return draft_for(ctx).rationale


def test_length_budget_fits_the_longest_rule_rationale() -> None:
    """上限必须容得下规则理由，否则模型只能删掉回测证据"""
    rationale = long_backtest_rationale()
    assert len(rationale) > 0
    assert len(rationale) <= RATIONALE_MAX_CHARS, (
        f"规则理由 {len(rationale)} 字，已超过上限 {RATIONALE_MAX_CHARS}"
    )
    assert str(RATIONALE_MAX_CHARS) in AdviceAdvisor.SYSTEM_PROMPT


# ==================== 6. 硬约束仍在 ====================


def test_system_prompt_keeps_the_hard_constraints() -> None:
    text = AdviceAdvisor.SYSTEM_PROMPT
    assert "不得修改" in text
    assert "不得编造任何数字" in text
    assert "rationale" in text, "要保留 JSON 输出格式说明"


def test_prompt_contains_rule_rationale_and_signals() -> None:
    ctx = make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)])
    draft = draft_for(ctx)
    prompt = AdviceAdvisor._build_prompt(ctx, draft)
    assert draft.rationale in prompt
    for signal in draft.signals:
        assert signal.summary in prompt


def test_prompt_never_leaks_enums_for_action() -> None:
    """动作要写成值，模型看到的是 BUY_NOW 而不是 AdviceAction.BUY_NOW"""
    ctx = make_ctx(900.0, prefs=AdvicePrefs(target_grams=60.0))
    draft = draft_for(ctx)
    prompt = AdviceAdvisor._build_prompt(ctx, draft)
    assert f"建议动作：{draft.action.value}" in prompt


# ==================== 6b. 关键约束在末尾重申 ====================


def test_critical_constraints_are_restated_at_the_end() -> None:
    """system prompt 距落笔位置较远，最关键的两条要在 user 末尾重申"""
    prompt = prompt_for(make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)]))
    tail = prompt[-260:]

    assert "【输出要求（重申）】" in tail
    assert "不得修改、重新计算或编造任何数字" in tail
    assert '"rationale"' in tail
    assert str(RATIONALE_MAX_CHARS) in tail


def test_restatement_is_the_last_section() -> None:
    """重申必须在最后一段，否则起不到 recency 作用"""
    prompt = prompt_for(make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)]))
    blocks = [line for line in prompt.splitlines() if line.startswith("【")]
    assert blocks[-1] == "【输出要求（重申）】"


# ==================== 6c. 缓存键覆盖 system prompt ====================


class _StubAI:
    """记录收到的 cache_key，并按顺序返回预设内容"""

    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, system_prompt, prompt, cache_key):
        self.calls.append({"system": system_prompt, "prompt": prompt, "cache": cache_key})
        return None


def test_cache_key_covers_the_system_prompt() -> None:
    """改了 system prompt 就必须换缓存键，否则 TTL 内会继续命中旧约束生成的措辞"""
    ctx = make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)])
    draft = draft_for(ctx)

    stub = _StubAI()
    advisor = AdviceAdvisor(ai_service=stub)
    advisor.phrase(ctx, draft)
    before = stub.calls[0]["cache"]

    # 只改 system prompt，user prompt 一个字不动
    original = AdviceAdvisor.SYSTEM_PROMPT
    try:
        AdviceAdvisor.SYSTEM_PROMPT = original + "\n（新增约束）"
        stub2 = _StubAI()
        AdviceAdvisor(ai_service=stub2).phrase(ctx, draft)
        after = stub2.calls[0]["cache"]
    finally:
        AdviceAdvisor.SYSTEM_PROMPT = original

    assert stub.calls[0]["prompt"] == stub2.calls[0]["prompt"], "前提：user prompt 完全一致"
    assert before != after, "system prompt 变了，缓存键必须跟着变"


def test_cache_key_is_stable_for_identical_input() -> None:
    ctx = make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)])
    draft = draft_for(ctx)
    stub = _StubAI()
    advisor = AdviceAdvisor(ai_service=stub)
    advisor.phrase(ctx, draft)
    advisor.phrase(ctx, draft)
    assert stub.calls[0]["cache"] == stub.calls[1]["cache"]


def test_unavailable_ai_falls_back_to_rule_rationale() -> None:
    ctx = make_ctx(990.0, lots=[lot(30.0, 900.0, is_opening=1)])
    draft = draft_for(ctx)
    rationale, model_info = AdviceAdvisor(ai_service=_StubAI()).phrase(ctx, draft)
    assert rationale == draft.rationale
    assert model_info == ""


# ==================== 7. 旧报警提示词已移除 ====================


def test_alert_era_prompt_is_gone() -> None:
    """旧 SYSTEM_PROMPT 与 analyze() 已随报警路径一并移除"""
    from service.ai_service import AIAnalysisService

    assert not hasattr(AIAnalysisService, "SYSTEM_PROMPT")
    assert not hasattr(AIAnalysisService, "analyze")
    assert not hasattr(AIAnalysisService, "_build_prompt")
    assert not hasattr(AIAnalysisService, "_parse_response")
    assert hasattr(AIAnalysisService, "complete"), "complete 仍在使用"


def test_no_should_alert_anywhere_in_service_layer() -> None:
    """should_alert 是报警时代的产物，服务层不该再有它"""
    root = Path(__file__).resolve().parent.parent / "service"
    hits = []
    for path in root.rglob("*.py"):
        if "should_alert" in path.read_text(encoding="utf-8"):
            hits.append(path.name)
    assert hits == [], f"仍残留 should_alert：{hits}"


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
