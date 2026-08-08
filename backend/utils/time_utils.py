"""时间工具 — 统一北京时间，避免每次手动传 CHINA_TZ"""

from datetime import datetime

from config import CHINA_TZ


def now() -> datetime:
    """当前北京时间（带时区）"""
    return datetime.now(CHINA_TZ)


def today() -> datetime:
    """今天 00:00:00 北京时间（带时区）"""
    return datetime.now(CHINA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


def from_timestamp(ts: float) -> datetime:
    """Unix 时间戳 → 北京时间（带时区）"""
    return datetime.fromtimestamp(ts, tz=CHINA_TZ)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """当前北京时间格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)


def today_str(fmt: str = "%Y-%m-%d") -> str:
    """今天日期格式化字符串"""
    return datetime.now(CHINA_TZ).strftime(fmt)
