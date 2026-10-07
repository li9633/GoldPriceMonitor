"""chinese-calendar 库源 —— 覆盖年份内权威、本地、零延迟。

覆盖范围有限（1.11.0 为 2004-2026），超出范围抛 `NotImplementedError`，
按契约返回 `UNKNOWN` 交由门面回退。
"""

from datetime import date

from providers.calendar.base import CalendarVerdict, TradingCalendarProvider
from utils.logger import get_logger

logger = get_logger("CalendarLib")


class ChineseCalendarLibProvider(TradingCalendarProvider):
    @property
    def name(self) -> str:
        return "chinese-calendar"

    def holiday_info(self, day: date) -> CalendarVerdict:
        try:
            from chinese_calendar import is_holiday
        except ImportError:
            return CalendarVerdict.UNKNOWN
        try:
            return (
                CalendarVerdict.KNOWN_HOLIDAY
                if is_holiday(day)
                else CalendarVerdict.KNOWN_WORKDAY
            )
        except NotImplementedError:
            return CalendarVerdict.UNKNOWN
        except Exception as exc:  # noqa: BLE001
            # 覆盖范围内的意外失败不该静默 —— 否则降级到在线源也查不到原因
            logger.warning("chinese-calendar 查询 %s 失败：%s", day, exc)
            return CalendarVerdict.UNKNOWN
