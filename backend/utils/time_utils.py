"""时间工具 — 统一北京时间，避免每次手动传 CHINA_TZ"""

import re
from datetime import date, datetime, timedelta, timezone

CHINA_TZ = timezone(timedelta(hours=8))

#: 只接受 YYYY-MM-DD
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

__all__ = [
    "CHINA_TZ",
    "InvalidDateError",
    "from_timestamp",
    "now",
    "now_str",
    "parse_date",
    "safe_date_str",
    "today",
    "today_end",
    "today_str",
]


class InvalidDateError(ValueError):
    """日期参数非法 —— 由 API 层转成 400，而不是冒泡成 500"""


def safe_date_str(value: str, field: str = "date") -> str:
    """校验日期字符串是合法的 YYYY-MM-DD，并原样返回。

    存在的意义是**拼接进 SQL 前的最后一道闸**：校验通过后字符串里
    只可能出现数字和短横线，拼进 `f"... >= '{value}'"` 才是安全的。

    用 `date(y, m, d)` 而不是 `strptime` 校验：`date` 会拒绝 2026-13-45、
    2026-02-30 这类不存在的日期，而且不涉及时区（避免「裸 datetime」问题）。
    """
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise InvalidDateError(f"{field} 必须是 YYYY-MM-DD 格式，收到 {value!r}")
    try:
        year, month, day = (int(part) for part in value.split("-"))
        date(year, month, day)
    except ValueError:
        raise InvalidDateError(f"{field} 不是合法日期：{value!r}") from None
    return value


def now() -> datetime:
    """当前北京时间（带时区）"""
    return datetime.now(CHINA_TZ)


def today() -> datetime:
    """今天 00:00:00 北京时间（带时区）"""
    return datetime.now(CHINA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


def today_end() -> datetime:
    """今天 23:59:59 北京时间（带时区）"""
    return datetime.now(CHINA_TZ).replace(hour=23, minute=59, second=59, microsecond=0)


def from_timestamp(ts: float) -> datetime:
    """Unix 时间戳 → 北京时间（带时区）"""
    return datetime.fromtimestamp(ts, tz=CHINA_TZ)


def parse_date(
    date_str: str, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    """日期字符串 'YYYY-MM-DD' → 北京时间 datetime

    非法输入抛 `InvalidDateError`（ValueError 子类）：这样 API 层能把它
    转成 400，而不是让一个手写的日期参数把请求打成 500。
    """
    safe_date_str(date_str)
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=hour, minute=minute, second=second, microsecond=0, tzinfo=CHINA_TZ
    )


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """当前北京时间格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)


def today_str(fmt: str = "%Y-%m-%d") -> str:
    """今天日期格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)
