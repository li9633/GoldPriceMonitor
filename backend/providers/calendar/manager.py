"""交易日历门面 —— 回退链 + 按天缓存 + 降级可观测（infra-refactor-plan §1）。

链路：`chinese-calendar（lib）→ haoshenqi（online）→ weekly-rule`。

- lib 覆盖年份内**权威**：本地、快、与国务院公告一致；
- lib 答不上来（覆盖范围外）→ 查**落库缓存**（既往在线结果）→ 在线源；
- weekly 兜底：永不失败，复现旧的「按星期判断」降级行为；
- 在线结果落库不设过期 —— 节假日安排一经公布不会回改；
- `status()` 暴露当前生效源与降级状态，供 /api/settings/calendar/status 查询。
"""

import threading
from datetime import date

from mapper.calendar_cache_mapper import CalendarCacheMapper
from providers.calendar.base import (
    CalendarResult,
    CalendarVerdict,
    TradingCalendarProvider,
)
from providers.calendar.chinese_lib import ChineseCalendarLibProvider
from providers.calendar.online import OnlineCalendarProvider
from providers.calendar.weekly import WeeklyRuleProvider
from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("TradingCalendar")


class TradingCalendar:
    def __init__(
        self,
        providers: list[TradingCalendarProvider] | None = None,
        cache: CalendarCacheMapper | None = None,
    ) -> None:
        self._providers = providers or [
            ChineseCalendarLibProvider(),
            OnlineCalendarProvider(),
            WeeklyRuleProvider(),
        ]
        self._cache = cache or CalendarCacheMapper()
        self._memory: dict[date, CalendarResult] = {}
        self._lock = threading.Lock()
        self._warned_sources: set[str] = set()

    # ==================== 查询 ====================

    def holiday_flag(self, day: date) -> bool | None:
        """`True` 休市日 / `False` 交易日 / `None` 全链 UNKNOWN（理论上不可达，
        weekly 兜底保证有值；保留 None 以防未来链路变更）"""
        result = self.resolve(day)
        if result.verdict is CalendarVerdict.UNKNOWN:
            return None
        return result.verdict is CalendarVerdict.KNOWN_HOLIDAY

    def resolve(self, day: date) -> CalendarResult:
        """按天解析（带内存缓存）。前两级「贵」的源各有兜底：
        lib 失败 → 落库缓存 → 在线；在线失败 → weekly。"""
        with self._lock:
            cached = self._memory.get(day)
        if cached is not None:
            return cached

        result = self._resolve_uncached(day)
        with self._lock:
            self._memory[day] = result
        self._maybe_warn(result)
        return result

    def _resolve_uncached(self, day: date) -> CalendarResult:
        lib = self._providers[0]
        verdict = lib.holiday_info(day)
        if verdict is not CalendarVerdict.UNKNOWN:
            return CalendarResult(verdict, lib.name)

        # lib 覆盖范围外：先看既往在线结果（含离线补过的数据）
        cached_verdict = self._cache.get(day)
        if cached_verdict is not None:
            return CalendarResult(
                CalendarVerdict(cached_verdict), f"{self._providers[1].name}(cached)"
            )

        online = self._providers[1]
        verdict = online.holiday_info(day)
        if verdict is not CalendarVerdict.UNKNOWN:
            self._cache.put(day, verdict.value, online.name)
            return CalendarResult(verdict, online.name)

        weekly = self._providers[-1]
        return CalendarResult(weekly.holiday_info(day), weekly.name)

    def _maybe_warn(self, result: CalendarResult) -> None:
        """降级到非权威源时告警一次（每次进程生命周期只告一次/源）"""
        source = result.source
        if source in self._warned_sources:
            return
        self._warned_sources.add(source)
        if result.source.startswith(OnlineCalendarProvider().name):
            logger.info("节假日判定使用在线源（lib 未覆盖该年份）")
        elif source == WeeklyRuleProvider().name:
            logger.warning(
                "节假日判定降级为按星期判断（lib 未覆盖且在线源不可用），"
                "法定节假日与调休将不被识别 —— 请升级 chinese-calendar 或检查网络"
            )

    # ==================== 观测 ====================

    def status(self) -> dict:
        """当前日历状态（供系统 API 暴露，让「今天是猜出来的」可被看见）"""
        lib = self._providers[0]
        online = self._providers[1]
        probe = now().date()
        result = self.resolve(probe)
        degraded = not result.source.startswith(lib.name)
        return {
            "active_source": result.source,
            "primary_source": lib.name,
            "online_source": online.name,
            "degraded": degraded,
            "cached_days": self._cache.count(),
        }


_calendar: TradingCalendar | None = None
_calendar_lock = threading.Lock()


def get_calendar() -> TradingCalendar:
    global _calendar
    with _calendar_lock:
        if _calendar is None:
            _calendar = TradingCalendar()
        return _calendar


def reset_calendar() -> None:
    """测试用：清空单例"""
    global _calendar
    with _calendar_lock:
        _calendar = None
