"""星期规则兜底 —— 永不失败、永不超范围。

对 SGE 而言：周末不开市（假日），周一至周五默认交易日。
这与 `market_session` 旧的降级行为完全一致 —— 日历库过期时退化为按星期判断。
"""

from datetime import date

from providers.calendar.base import CalendarVerdict, TradingCalendarProvider


class WeeklyRuleProvider(TradingCalendarProvider):
    @property
    def name(self) -> str:
        return "weekly-rule"

    def holiday_info(self, day: date) -> CalendarVerdict:
        if day.weekday() >= 5:
            return CalendarVerdict.KNOWN_HOLIDAY
        return CalendarVerdict.KNOWN_WORKDAY
