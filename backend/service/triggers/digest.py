"""每日摘要触发器 —— 每天固定时间一条，回答「黄金现在怎样了 + 对我影响」。

时间默认 20:00（正好 SGE 夜盘开盘，看完当晚有操作依据）。
仅在 NORMAL / INTL_ONLY 生效：周末双休市价格冻结，摘要没有信息量，
也无需为它豁免静默闸门 —— 它自然服从现有流程。
"""

from channels.base import KIND_DIGEST, NotificationData
from service.triggers.base import (
    NotificationEvent,
    TickContext,
    Trigger,
    TriggerOutcome,
)
from service.triggers.notify_common import (
    fmt_pct,
    is_after,
    pct_change,
    position_summary,
    price_24h_change,
    trigger_config,
)
from utils.logger import get_logger

logger = get_logger("DigestTrigger")


class DailyDigestTrigger(Trigger):
    def __init__(self, settings, price_mapper, portfolio_mapper) -> None:
        self.settings = settings
        self.price_mapper = price_mapper
        self.portfolio_mapper = portfolio_mapper
        # 内存去重（进程重启后同日可能重发一次，可接受）
        self._sent_dates: set[str] = set()

    @property
    def name(self) -> str:
        return "digest"

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        config = trigger_config(self.settings)
        if not config["digest_enabled"] or not tick.decision.allowed:
            return TriggerOutcome()
        if tick.decision.policy.name not in ("NORMAL", "INTL_ONLY"):
            return TriggerOutcome()
        if not is_after((tick.at.hour, tick.at.minute), str(config["digest_time"])):
            return TriggerOutcome()

        day = tick.at.date().isoformat()
        if day in self._sent_dates:
            return TriggerOutcome()
        self._sent_dates.add(day)

        fields: dict[str, str] = {}
        price = tick.market_price
        # 「当前价格」由通用模板的固定行展示，不放进 fields（避免重复渲染）
        change_24h = price_24h_change(
            self.price_mapper, tick.market_symbol or tick.main_symbol
        )
        if change_24h is not None:
            fields["24 小时涨跌"] = fmt_pct(change_24h)
        if tick.london_usd and tick.london_usd > 0:
            fields["国际金"] = f"${tick.london_usd:.2f}"

        # INTL_ONLY：主品种价格冻结（节前收盘），给出假期累计参考
        if tick.market_symbol:
            main = tick.prices_data.get(tick.main_symbol) or {}
            sge_close = main.get("price")
            cumulative = pct_change(price, float(sge_close)) if sge_close else None
            if cumulative is not None:
                fields["较节前收盘"] = fmt_pct(cumulative)

        position = (
            position_summary(self.portfolio_mapper, tick.main_symbol, price)
            if price > 0
            else None
        )
        if position:
            fields.update(position)
        if tick.valuation_note:
            fields["说明"] = tick.valuation_note

        summary = f"每日行情摘要（{day}）"
        logger.info(f"推送每日摘要：{day}")
        return TriggerOutcome(
            events=[
                NotificationEvent(
                    kind=KIND_DIGEST,
                    symbol=tick.main_symbol,
                    dedup_key=f"{tick.main_symbol}#digest#{day}",
                    urgency="low",
                    cooldown_minutes=0.0,  # 去重由「每天一次」保证
                    price_basis=price,
                    current_price=price,
                    summary=summary,
                    notification=NotificationData(
                        kind=KIND_DIGEST,
                        symbol=tick.main_symbol,
                        symbol_name=self.settings.get_symbol_name_map().get(
                            tick.main_symbol, tick.main_symbol
                        ),
                        current_price=price,
                        fields=fields,
                        alert_level="info",
                        summary=summary,
                    ),
                )
            ]
        )
