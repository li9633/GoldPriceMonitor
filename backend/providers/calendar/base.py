"""交易日历抽象 —— 调用方不关心数据源与回退（infra-refactor-plan §1）。

判定契约：
- `KNOWN_HOLIDAY`：确定是休市日（法定节假日 / 周末）；
- `KNOWN_WORKDAY`：确定是交易日（含调休上班的周末 —— 对交易所无意义，
  周末是否开市由 `market_session` 的 weekday 判定负责，日历只答「假日与否」）；
- `UNKNOWN`：本源答不上来（覆盖范围外 / 请求失败 / 依赖缺失），由门面决定回退。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum


class CalendarVerdict(Enum):
    KNOWN_HOLIDAY = "holiday"
    KNOWN_WORKDAY = "workday"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CalendarResult:
    verdict: CalendarVerdict
    source: str


class TradingCalendarProvider(ABC):
    """节假日数据源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def holiday_info(self, day: date) -> CalendarVerdict: ...
