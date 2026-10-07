"""haoshenqi 在线源 —— lib 过期年份的接棒者。

2026-10-07 探测结论（scripts/probe_holiday_apis.py）：
- 判定方向全部正确：status 0=工作日 / 1=周末 / 2=调休上班 / 3=法定假日；
- 2026 覆盖完整；2027 尚未返回数据（国务院 2027 安排未发布，属预期行为）；
- timor.tech 同日探测不稳定（超时 / 403），故选 haoshenqi 为首选在线源。

结果**必须**由门面缓存落库 —— 本源可用性一般，热路径不允许反复请求。
"""

from datetime import date

import requests

from providers.calendar.base import CalendarVerdict, TradingCalendarProvider
from utils.logger import get_logger

logger = get_logger("CalendarOnline")

_API_URL = "https://api.haoshenqi.top/holiday"
_TIMEOUT = 5.0

#: status → 判定（3=法定假日，1=周末，0/2=工作日含调休上班）
_STATUS_HOLIDAY = {1, 3}


class OnlineCalendarProvider(TradingCalendarProvider):
    @property
    def name(self) -> str:
        return "haoshenqi"

    def holiday_info(self, day: date) -> CalendarVerdict:
        try:
            resp = requests.get(
                _API_URL, params={"date": day.isoformat()}, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("haoshenqi 查询 %s 失败：%s", day, exc)
            return CalendarVerdict.UNKNOWN

        # 响应形态不统一：多数日期返回对象，个别日期返回列表
        if isinstance(data, list):
            data = next(
                (item for item in data if item.get("date") == day.isoformat()),
                data[0] if data else None,
            )
        if not isinstance(data, dict) or "status" not in data:
            logger.warning("haoshenqi 返回结构异常：%s", str(data)[:120])
            return CalendarVerdict.UNKNOWN

        try:
            status = int(data["status"])
        except (TypeError, ValueError):
            return CalendarVerdict.UNKNOWN
        return (
            CalendarVerdict.KNOWN_HOLIDAY
            if status in _STATUS_HOLIDAY
            else CalendarVerdict.KNOWN_WORKDAY
        )
