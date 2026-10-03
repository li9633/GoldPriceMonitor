"""通知渲染测试：建议类消息必须读起来像「建议」而不是「报警」。

覆盖 `MessageTemplate.format_advice` 的 markdown 与 email 两条路径，
以及 `NotificationService.send_advice` 从建议记录构造载荷的取值来源
（持仓上下文必须来自建议冻结的 `evidence`，而不是当前的实时持仓）。

运行
----
    cd backend
    python -m test.test_advice_notification
"""

import datetime

from channels.base import AdviceData, AdvicePayload
from models.advice import (
    AdviceAction,
    AdviceKind,
    AdviceRecord,
    AdviceStatus,
    Signal,
    SignalCategory,
)
from service.notification_service import NotificationService
from utils.message_template import MessageTemplate


def make_record(action: AdviceAction = AdviceAction.BUY_PARTIAL) -> AdviceRecord:
    return AdviceRecord(
        id=42,
        created_at="2025-09-24 10:00:00",
        kind=AdviceKind.PRE_PURCHASE,
        action=action,
        symbol="gds_AUTD",
        target_grams=20.0,
        price_band_low=902.0,
        price_band_high=914.0,
        confidence=0.65,
        rationale="处于近 24 小时区间上沿，建议分批买入。",
        signals=[
            Signal(
                id="near_24h_high",
                category=SignalCategory.MARKET,
                severity="info",
                summary="处于近 24 小时区间上沿",
            ),
            Signal(
                id="no_position",
                category=SignalCategory.POSITION,
                severity="info",
                summary="当前没有持仓",
            ),
        ],
        evidence={
            "position": {
                "total_grams": 30.0,
                "avg_cost": 900.0,
                "unrealized_pnl": -120.0,
                "unrealized_pnl_pct": -0.44,
            }
        },
        status=AdviceStatus.DELIVERED,
    )


def make_alert_data(action: AdviceAction = AdviceAction.BUY_PARTIAL) -> AdviceData:
    record = make_record(action)
    position = record.evidence["position"]
    return AdviceData(
        symbol=record.symbol,
        symbol_name="黄金T+D",
        current_price=909.0,
        extra_info={"london_gold_cny": 531.2, "london_gold_usd": 2300.0},
        advice=AdvicePayload(
            action=action.value,
            rationale=record.rationale,
            target_grams=record.target_grams,
            price_band_low=record.price_band_low,
            price_band_high=record.price_band_high,
            confidence=record.confidence,
            signals=[s.summary for s in record.signals],
            total_grams=position["total_grams"],
            avg_cost=position["avg_cost"],
            unrealized_pnl=position["unrealized_pnl"],
            unrealized_pnl_pct=position["unrealized_pnl_pct"],
            advice_id=record.id,
        ),
    )


# ==================== 载荷 ====================


def test_payload_carries_action_and_numbers() -> None:
    data = make_alert_data()
    assert data.advice.action == "BUY_PARTIAL"
    assert data.advice.target_grams == 20.0
    assert data.alert_level == "warning"
    assert data.advice.subject_lot_id is None, "非复盘建议不带买入关联"


# ==================== Markdown（企业微信） ====================


def test_markdown_advice_renders_action_and_numbers() -> None:
    message = MessageTemplate.format_advice(make_alert_data(), template_type="markdown")

    assert "[建议]" in message
    assert "建议分批买入" in message, "动作应显示为中文标签"
    assert "20.0 克" in message
    assert "¥902.00 ~ ¥914.00" in message
    assert "30.0g" in message and "¥900.00" in message, "应带上持仓成本上下文"
    assert "-0.44%" in message
    assert "处于近 24 小时区间上沿" in message, "信号应作为判断依据列出"
    assert "建议分批买入。" in message, "理由应出现在说明里"
    assert "不构成投资建议" in message, "建议类消息必须带免责声明"
    assert "报警" not in message, "建议消息不应出现「报警」字样"
    assert "531.2" in message, "伦敦金参考应保留"


def test_markdown_advice_without_position() -> None:
    data = make_alert_data()
    data.advice.total_grams = None
    message = MessageTemplate.format_advice(data, template_type="markdown")
    assert "暂无持仓" in message


def test_markdown_advice_without_grams_says_so() -> None:
    data = make_alert_data()
    data.advice.target_grams = None
    message = MessageTemplate.format_advice(data, template_type="markdown")
    assert "本次不涉及数量" in message


def test_markdown_action_labels_and_colors() -> None:
    for action, label in MessageTemplate.ACTION_LABELS.items():
        data = make_alert_data(AdviceAction(action))
        message = MessageTemplate.format_advice(data, template_type="markdown")
        assert label in message
        color = MessageTemplate.ACTION_COLORS.get(action, "#8c7a5c")
        assert color in message


def test_markdown_escapes_markdown_specials() -> None:
    data = make_alert_data()
    data.advice.rationale = "价格 *跌破* 关键位 [注意]"
    message = MessageTemplate.format_advice(data, template_type="markdown")
    assert r"\*跌破\*" in message
    assert r"\[注意\]" in message


# ==================== Email ====================


def test_email_advice_renders_template() -> None:
    message = MessageTemplate.format_advice(make_alert_data(), template_type="email")

    assert "<!doctype html>" in message.lower()
    assert "黄金持仓建议" in message
    assert "建议分批买入" in message
    assert "20.0 克" in message
    assert "¥902.00 ~ ¥914.00" in message
    assert "处于近 24 小时区间上沿" in message
    assert "{{" not in message, "所有占位符都应被替换"
    assert "不构成投资建议" in message


def test_email_advice_escapes_html() -> None:
    data = make_alert_data()
    data.advice.rationale = '价格 <b>跌破</b> "关键位"'
    message = MessageTemplate.format_advice(data, template_type="email")
    assert "&lt;b&gt;" in message
    assert "<b>跌破</b>" not in message


# ==================== 从建议记录构造载荷 ====================


class RecordingChannel:
    """只记录收到的载荷，不发网络请求"""

    channel_type = "recording"
    channel_name = "记录渠道"

    def __init__(self):
        self.received: list[AdviceData] = []

    def send(self, data, config):
        from channels.base import ChannelResult

        self.received.append(data)
        return ChannelResult(success=True, channel_type=self.channel_type)


def test_send_advice_builds_payload_from_frozen_evidence() -> None:
    service = object.__new__(NotificationService)

    class FakeSettings:
        def get_symbol_name_map(self):
            return {"gds_AUTD": "黄金T+D"}

        def get_notification_strategy(self):
            return {"stop_on_first_success": True}

    service.settings = FakeSettings()
    service._get_channel_configs = lambda: [
        {"channel_type": "recording", "display_name": "记录渠道", "enabled": True,
         "priority": 1}
    ]
    recorded: list[dict] = []
    service._record_log = lambda *args, **kwargs: recorded.append(kwargs)

    channel = RecordingChannel()
    import channels as channels_module

    channels_module._registry["recording"] = channel

    result = service.send_advice(make_record(), current_price=909.0)
    assert result is True
    assert len(channel.received) == 1

    data = channel.received[0]
    assert data.advice.action == "BUY_PARTIAL"
    assert data.advice.target_grams == 20.0
    # 持仓上下文来自建议冻结的 evidence（30g @900），不是当前实时持仓
    assert data.advice.total_grams == 30.0
    assert data.advice.avg_cost == 900.0
    assert data.advice.unrealized_pnl_pct == -0.44
    assert data.advice.advice_id == 42
    assert data.advice.signals == ["处于近 24 小时区间上沿", "当前没有持仓"]
    assert data.alert_level == "warning", "BUY_PARTIAL → warning（前端按此上色）"
    assert recorded, "应记录通知发送日志"


def test_send_advice_level_for_stop_loss() -> None:
    service = object.__new__(NotificationService)

    class FakeSettings:
        def get_symbol_name_map(self):
            return {"gds_AUTD": "黄金T+D"}

        def get_notification_strategy(self):
            return {"stop_on_first_success": True}

    service.settings = FakeSettings()
    captured: list[dict] = []

    class CaptureChannel(RecordingChannel):
        channel_type = "capture"

    channel = CaptureChannel()
    import channels as channels_module

    channels_module._registry["capture"] = channel
    service._get_channel_configs = lambda: [
        {"channel_type": "capture", "display_name": "捕获", "enabled": True, "priority": 1}
    ]
    service._record_log = lambda *args, **kwargs: captured.append(kwargs)

    service.send_advice(make_record(AdviceAction.STOP_LOSS), current_price=800.0)
    assert channel.received[0].alert_level == "critical"


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
