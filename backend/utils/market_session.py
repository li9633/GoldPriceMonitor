"""市场时段判断与消息发送策略。

背景
----
原先用 `ModelPool` 的 60 分钟缓存来「避免休市期间消息轰炸」，但缓存返回的是同一个
`should_alert` 布尔值，而发送判断只看这个布尔值 —— 缓存实际上会让同一个判断被反复
执行，并不能抑制发送。本模块把「发不发」独立出来：按 SGE 与国际金各自的开市状态，
决定是否发送、以及是否需要调用 AI。

两个市场的时段
--------------
- **SGE Au(T+D)**：日盘 09:00-11:30 / 13:30-15:30，夜盘 20:00-次日 02:30（可配置）。
  周末与法定节假日休市 —— 注意**调休上班的周末同样休市**。
- **国际金（伦敦/COMEX）**：北京时间周一早间开盘、周六早间收盘，周末休市。

判定原则
--------
**不确定时判为休市。** 宁可少发一条，也不在停市、价格停滞时刷屏。
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from enum import Enum

from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("MarketSession")


class Session(Enum):
    """单个市场的开市状态"""

    OPEN = "open"
    CLOSED = "closed"  # 交易日内的非交易时段
    WEEKEND = "weekend"  # 周末休市
    HOLIDAY = "holiday"  # 法定节假日休市


class SendPolicy(Enum):
    """综合两个市场后的消息发送策略"""

    NORMAL = "normal"  # 两个市场都开市
    INTL_ONLY = "intl_only"  # SGE 休市、国际金开市：照常发，但口径切到国际金
    LOW_FREQ = "low_freq"  # SGE 开市、国际金休市：仅高优先级
    SILENT = "silent"  # 两个市场都休市：不发送，也不调用 AI


# ==================== 配置读取 ====================

#: 交易时段默认值，与 `MonitorConfigModel.trading_hours` 保持一致
_DEFAULT_HOURS: list[tuple[str, str]] = [
    ("09:00", "11:30"),
    ("13:30", "15:30"),
    ("20:00", "23:59"),
    ("00:00", "02:30"),
]

#: 起始时间早于该分钟数的窗口，视为**上一交易日夜间盘的延续**，归属前一个交易日。
#: 默认配置里的 00:00-02:30 就属于这种窗口。
_NIGHT_TAIL_CUTOFF_MINUTES = 6 * 60

_HOURS_TTL_SECONDS = 60.0
_hours_lock = threading.Lock()
_hours_cache: tuple[float, list[tuple[int, int, int]]] | None = None


def _read_trading_hours() -> list[tuple[str, str]]:
    """从系统设置读取交易时段（惰性导入以避免循环依赖）"""
    from service.system_settings_service import SystemSettingsService

    raw = SystemSettingsService().get_monitor_config().get("trading_hours", [])
    if not raw or isinstance(raw, str):
        return _DEFAULT_HOURS
    return [(str(s), str(e)) for s, e in raw]


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _normalize(raw: list[tuple[str, str]]) -> list[tuple[int, int, int]]:
    """把配置窗口规范化成 `(归属日偏移, 起始分钟, 结束分钟)`。

    偏移 -1 表示该窗口归属**前一个交易日**（夜间盘的凌晨部分）。

    同时支持两种配置写法：
    - 拆开写：`20:00-23:59` + `00:00-02:30`（默认配置）
    - 合并写：`20:00-02:30`
    """
    normalized: list[tuple[int, int, int]] = []
    for start_str, end_str in raw:
        start, end = _to_minutes(start_str), _to_minutes(end_str)
        if start > end:
            # 单一跨午夜窗口：晚间部分归当天，凌晨部分归前一日
            normalized.append((0, start, 24 * 60 - 1))
            normalized.append((-1, 0, end))
        elif start < _NIGHT_TAIL_CUTOFF_MINUTES:
            # 凌晨窗口：属于前一交易日夜盘的延续
            normalized.append((-1, start, end))
        else:
            normalized.append((0, start, end))
    return normalized


def trading_windows() -> list[tuple[int, int, int]]:
    """规范化的交易窗口，带 60 秒缓存（避免每次巡检都查一次数据库）"""
    global _hours_cache
    current = time.monotonic()
    with _hours_lock:
        if _hours_cache is not None and current - _hours_cache[0] < _HOURS_TTL_SECONDS:
            return _hours_cache[1]
    normalized = _normalize(_read_trading_hours())
    with _hours_lock:
        _hours_cache = (current, normalized)
    return normalized


def invalidate_cache() -> None:
    """清空交易时段缓存（配置变更后调用，或测试中使用）"""
    global _hours_cache
    with _hours_lock:
        _hours_cache = None


# ==================== 交易日与节假日 ====================


def _holiday_flag(day: date) -> bool | None:
    """`True` 法定节假日 / `False` 非节假日 / `None` 全链无法判定。

    判定委托给 `providers.calendar` 的回退链
    （chinese-calendar → 在线源 → 星期规则），本模块不再直接依赖具体日历库。
    历史背景：`chinese_calendar.is_workday()` 对调休上班的周末返回 `True`，
    但交易所周末从不开市 —— 该边界已由链路的 lib 源用 `is_holiday()` 处理。
    """
    from providers.calendar import get_calendar

    return get_calendar().holiday_flag(day)


def is_trading_day(day: date) -> bool:
    """SGE 是否为交易日：周一至周五，且不是法定节假日。

    注意**不能**用 `chinese_calendar.is_workday()`：它对调休上班的周末返回 `True`
    （例如 2025-09-28 周日、2025-10-11 周六），但交易所周末从不开市。
    """
    if day.weekday() >= 5:
        return False
    holiday = _holiday_flag(day)
    return True if holiday is None else not holiday


def _closed_kind(day: date) -> Session:
    if day.weekday() >= 5:
        return Session.WEEKEND
    if _holiday_flag(day):
        return Session.HOLIDAY
    return Session.CLOSED


# ==================== SGE 时段 ====================


def sge_session(at: datetime | None = None) -> Session:
    """SGE Au(T+D) 当前开市状态"""
    at = at or now()
    minutes = at.hour * 60 + at.minute
    for offset, start, end in trading_windows():
        if start <= minutes <= end:
            owner = at.date() + timedelta(days=offset)
            if is_trading_day(owner):
                return Session.OPEN
    return _closed_kind(at.date())


# ==================== 国际金时段 ====================

#: 国际金每周收盘：北京时间周六早晨。夏令时 05:00 / 冬令时 06:00。
#: 收盘时间随夏令时浮动，按「不确定时判为休市」取**较早**的 05:00。
INTL_WEEKLY_CLOSE_HOUR = 5

#: 国际金每周开盘：北京时间周一早晨。夏令时 06:00 / 冬令时 07:00。
#: 按同一原则取**较晚**的 07:00。
INTL_WEEKLY_OPEN_HOUR = 7


def intl_session(at: datetime | None = None) -> Session:
    """国际金（伦敦/COMEX）当前开市状态。

    只按「星期几 + 宽松边界」判断，不写死精确时间点，以避开夏令时那 1 小时的误差。
    国际金假日（圣诞、元旦、感恩节半日市）暂不覆盖。
    """
    at = at or now()
    weekday = at.date().weekday()
    hour = at.hour

    if weekday == 5:  # 周六：早晨收盘前仍算开市（延续周五夜盘）
        return Session.OPEN if hour < INTL_WEEKLY_CLOSE_HOUR else Session.WEEKEND
    if weekday == 6:  # 周日：全天休市
        return Session.WEEKEND
    if weekday == 0:  # 周一：早晨开盘前仍算休市
        return Session.OPEN if hour >= INTL_WEEKLY_OPEN_HOUR else Session.WEEKEND
    return Session.OPEN  # 周二至周五全天开市


# ==================== 综合策略 ====================


def policy_for(sge: Session, intl: Session) -> SendPolicy:
    """由两个市场的状态推导发送策略（2×2 矩阵）"""
    sge_open = sge is Session.OPEN
    intl_open = intl is Session.OPEN
    if sge_open and intl_open:
        return SendPolicy.NORMAL
    if sge_open:
        return SendPolicy.LOW_FREQ
    if intl_open:
        return SendPolicy.INTL_ONLY
    return SendPolicy.SILENT


def send_policy(at: datetime | None = None) -> SendPolicy:
    """当前发送策略"""
    at = at or now()
    return policy_for(sge_session(at), intl_session(at))


def describe(sge: Session | None = None, intl: Session | None = None) -> str:
    """人话描述当前时段，用于日志与 prompt"""
    sge = sge if sge is not None else sge_session()
    intl = intl if intl is not None else intl_session()
    policy = policy_for(sge, intl)

    sge_text = {
        Session.OPEN: "SGE 交易中",
        Session.CLOSED: "SGE 非交易时段",
        Session.WEEKEND: "SGE 周末休市",
        Session.HOLIDAY: "SGE 法定节假日休市",
    }[sge]
    intl_text = {
        Session.OPEN: "国际金交易中",
        Session.CLOSED: "国际金非交易时段",
        Session.WEEKEND: "国际金周末休市",
        Session.HOLIDAY: "国际金休市",
    }[intl]
    policy_text = {
        SendPolicy.NORMAL: "正常推送",
        SendPolicy.INTL_ONLY: "仅参考国际金，照常推送",
        SendPolicy.LOW_FREQ: "仅推送高优先级",
        SendPolicy.SILENT: "休市静默，不推送也不调用 AI",
    }[policy]
    return f"{sge_text}；{intl_text}；{policy_text}"
