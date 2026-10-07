"""通知阶段 A：载荷泛化测试。

`AdviceData` → `NotificationData(kind)` 之后：

1. advice / review 走建议模板，渲染结果与泛化前一致；
2. 非 advice 类消息（digest 等）走通用模板，fields 逐行展开；
3. 未知 kind 兜底走通用模板（新增类型零渠道改动）；
4. 邮件主题按 kind 区分；
5. `NotificationService.send()` 拒绝建议类消息（必须走 send_advice）；
6. `AdviceData` 别名保持旧代码可用。

运行
----
    cd backend
    python -m test.test_notification_payload
"""

from channels import (
    KIND_ADVICE,
    KIND_DIGEST,
    KIND_REVIEW,
    KIND_VOLATILITY,
    AdviceData,
    AdvicePayload,
    NotificationData,
)
from service.notification_service import NotificationService
from utils.message_template import MessageTemplate


def _advice_data(kind: str = KIND_ADVICE) -> NotificationData:
    return NotificationData(
        kind=kind,
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        current_price=909.0,
        extra_info={"london_gold_cny": 531.2, "london_gold_usd": 2300.0},
        advice=AdvicePayload(
            action="BUY_PARTIAL",
            rationale="现价贴近 90 日低点",
            target_grams=20.0,
            price_band_low=905.0,
            price_band_high=915.0,
            confidence=0.6,
            signals=["贴近近 90 日低点，仅高 0.4%"],
            total_grams=50.0,
            avg_cost=928.0,
            unrealized_pnl=-120.0,
            unrealized_pnl_pct=-0.44,
        ),
    )


def test_advice_kind_renders_via_advice_template() -> None:
    """advice 走建议模板：动作标签、价位区间、持仓上下文齐全"""
    md = MessageTemplate.format(KIND_ADVICE, _advice_data(), template_type="markdown")
    assert "建议分批买入" in md
    assert "¥905.00 ~ ¥915.00" in md
    assert "50.0g" in md


def test_review_kind_also_uses_advice_template() -> None:
    """review 与 advice 共用建议模板"""
    data = _advice_data(KIND_REVIEW)
    md = MessageTemplate.format(KIND_REVIEW, data, template_type="markdown")
    assert "建议分批买入" in md


def test_generic_kind_renders_fields_markdown() -> None:
    """digest 走通用模板：标题 + fields 逐行展开"""
    data = NotificationData(
        kind=KIND_DIGEST,
        symbol="hf_XAU",
        symbol_name="伦敦金",
        current_price=2330.5,
        fields={
            "昨日涨跌": "+1.2%",
            "假期累计": "+2.1%",
            "折算人民币": "¥531/g",
        },
    )
    md = MessageTemplate.format(KIND_DIGEST, data, template_type="markdown")
    assert "黄金每日行情摘要" in md
    assert "**昨日涨跌**：+1.2%" in md
    assert "假期累计" in md


def test_generic_kind_renders_fields_email() -> None:
    """通用模板的 email 渲染包含标题与字段"""
    data = NotificationData(
        kind=KIND_VOLATILITY,
        symbol_name="伦敦金",
        current_price=2330.5,
        fields={"较节前收盘": "+1.5%"},
    )
    html = MessageTemplate.format(KIND_VOLATILITY, data, template_type="email")
    assert "黄金价格波动提醒" in html
    assert "较节前收盘" in html
    assert "<html" in html


def test_unknown_kind_falls_back_to_generic() -> None:
    """未登记的 kind 兜底走通用模板，kind 原样作为标题"""
    data = NotificationData(kind="mystery", fields={"a": "b"})
    md = MessageTemplate.format("mystery", data, template_type="markdown")
    assert "mystery" in md
    assert "**a**：b" in md


def test_email_subject_by_kind() -> None:
    """邮件主题：建议带动作标签，通用带 kind 标题"""
    advice_subject = _advice_subject(_advice_data())
    assert advice_subject.startswith("[建议] 建议分批买入")
    digest = NotificationData(
        kind=KIND_DIGEST, symbol_name="伦敦金", current_price=2330.5
    )
    assert _advice_subject(digest) == "[黄金每日行情摘要] 伦敦金 - 2330.50"


def _advice_subject(data: NotificationData) -> str:
    """复现 email_channel 的主题拼装逻辑供断言"""
    from channels.base import ADVICE_KINDS
    from service.notification_service import NotificationService as _S  # noqa: F401

    if data.kind in ADVICE_KINDS:
        label = MessageTemplate.ACTION_LABELS.get(
            data.advice.action, data.advice.action
        )
        return f"[建议] {label} - {data.symbol_name} - {data.current_price:.2f}"
    return (
        f"[{MessageTemplate.kind_title(data.kind)}] "
        f"{data.symbol_name} - {data.current_price:.2f}"
    ).rstrip(" -")


def test_send_rejects_advice_kind() -> None:
    """建议类消息必须走 send_advice，send() 直接拒绝"""
    service = NotificationService()
    try:
        service.send(_advice_data())
    except AssertionError:
        return
    raise AssertionError("send() 应拒绝 advice 类消息")


def test_advice_data_alias_still_works() -> None:
    """AdviceData 别名保持旧构造方式可用"""
    data = AdviceData(
        symbol="gds_AUTD",
        symbol_name="黄金T+D",
        current_price=909.0,
        advice=AdvicePayload(action="HOLD"),
    )
    assert data.kind == KIND_ADVICE
    assert data.advice is not None and data.advice.action == "HOLD"


def test_format_advice_requires_payload() -> None:
    """建议模板缺 advice 载荷时报错"""
    try:
        MessageTemplate.format(
            KIND_ADVICE, NotificationData(kind=KIND_ADVICE), template_type="markdown"
        )
    except ValueError:
        return
    raise AssertionError("缺 advice 载荷应抛 ValueError")


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
