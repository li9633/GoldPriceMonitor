"""时间工具 — 统一北京时间，避免每次手动传 CHINA_TZ"""

from datetime import datetime, timedelta, timezone

CHINA_TZ = timezone(timedelta(hours=8))

__all__ = [
    "CHINA_TZ",
    "from_timestamp",
    "now",
    "now_str",
    "parse_date",
    "today",
    "today_end",
    "today_str",
]


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
    """日期字符串 'YYYY-MM-DD' → 北京时间 datetime"""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=hour, minute=minute, second=second, microsecond=0, tzinfo=CHINA_TZ
    )


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """当前北京时间格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)


def today_str(fmt: str = "%Y-%m-%d") -> str:
    """今天日期格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)
