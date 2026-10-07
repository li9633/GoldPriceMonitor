"""节后缺口预告触发器 —— 假期最后一个晚上，预告节后开盘方向。

条件：今天 SGE 休市且为**法定节假日**、明天是交易日、到点（默认 20:00）。
普通周末不触发（周日预告的信息周五收盘后就已知，只会变噪音）。
每假期自然只发一条（条件一天只满足一次 + 按日去重）。
"""

import datetime

from channels.base import KIND_REOPEN_GAP, NotificationData
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
    trigger_config,
)
from utils.logger import get_logger
from utils.market_session import SendPolicy, is_trading_day

logger = get_logger("ReopenGapTrigger")


class ReopenGapTrigger(Trigger):
    def __init__(self, settings, price_mapper, portfolio_mapper, calendar=None) -> None:
        self.settings = settings
        self.price_mapper = price_mapper
        self.portfolio_mapper = portfolio_mapper
        self._calendar = calendar
        self._sent_dates: set[str] = set()

    @property
    def name(self) -> str:
        return "reopen_gap"

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        config = trigger_config(self.settings)
        if not config["reopen_gap_enabled"] or not tick.decision.allowed:
            return TriggerOutcome()
        # 缺口预告只在国际金开市的假期（INTL_ONLY）有意义
        if tick.decision.policy is not SendPolicy.INTL_ONLY:
            return TriggerOutcome()

        today = tick.at.date()
        from providers.calendar import get_calendar

        calendar = self._calendar or get_calendar()
        if calendar.holiday_flag(today) is not True:
            return TriggerOutcome()  # 仅法定节假日（周末不算）
        if not is_trading_day(today + datetime.timedelta(days=1)):
            return TriggerOutcome()
        if not is_after((tick.at.hour, tick.at.minute), str(config["reopen_gap_time"])):
            return TriggerOutcome()

        day = today.isoformat()
        if day in self._sent_dates:
            return TriggerOutcome()
        self._sent_dates.add(day)

        main = tick.prices_data.get(tick.main_symbol) or {}
        sge_close = main.get("price")
        price = tick.market_price
        gap = pct_change(price, float(sge_close)) if sge_close else None

        fields: dict[str, str] = {
            "节前收盘": f"¥{float(sge_close):.2f}/g" if sge_close else "—",
            "假期国际金现价": f"¥{price:.2f}/g",
            "假期累计": fmt_pct(gap),
        }
        if gap is not None:
            fields["预计开盘方向"] = "高开" if gap > 0 else ("低开" if gap < 0 else "平开")
        if tick.london_usd and tick.london_usd > 0:
            fields["国际金"] = f"${tick.london_usd:.2f}"
        position = position_summary(
            self.portfolio_mapper, tick.main_symbol, price
        )
        if position:
            fields.update(position)
        fields["说明"] = tick.valuation_note or (
            "预估基于国际金折算价，可能与实际开盘价存在偏差"
        )

        summary = f"节后开盘预告（{day}）"
        logger.info(f"推送节后缺口预告：{day}")
        return TriggerOutcome(
            events=[
                NotificationEvent(
                    kind=KIND_REOPEN_GAP,
                    symbol=tick.main_symbol,
                    dedup_key=f"{tick.main_symbol}#reopen_gap#{day}",
                    urgency="medium",
                    cooldown_minutes=0.0,
                    price_basis=price,
                    current_price=price,
                    summary=summary,
                    notification=NotificationData(
                        kind=KIND_REOPEN_GAP,
                        symbol=tick.main_symbol,
                        symbol_name=self.settings.get_symbol_name_map().get(
                            tick.main_symbol, tick.main_symbol
                        ),
                        current_price=price,
                        fields=fields,
                        alert_level="warning",
                        summary=summary,
                    ),
                )
            ]
        )
