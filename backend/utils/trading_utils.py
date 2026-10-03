"""交易时段工具。

具体判断逻辑已统一到 `utils.market_session`，本模块只保留既有的公开函数名，避免
两处逻辑打架（`ai_service` 目前在 prompt 里调用 `get_trading_status_text()`）。

修复的两个历史问题：
- 原先用 `chinese_calendar.is_workday()` 判断交易日，而它对**调休上班的周末**返回
  `True`（如 2025-09-28 周日），会把休市的周末误判成交易时段；
- 原先用**当天**的工作日状态判断 `00:00-02:30` 窗口，而该窗口属于**前一个交易日**
  的夜间盘，导致周六凌晨（周五夜盘尚未结束）被判为休市。
"""

from utils.market_session import Session, intl_session, sge_session


def is_autd_trading() -> bool:
    """当前是否在 Au(T+D) 交易时段内

    自动处理：周末、法定节假日、调休、夜盘跨日。
    """
    return sge_session() is Session.OPEN


def get_trading_status_text() -> str:
    """当前两个市场的开市状态描述，供 AI prompt 使用"""
    sge = sge_session()
    intl = intl_session()

    if sge is Session.OPEN and intl is Session.OPEN:
        return "Au(T+D) 与国际金均在交易，价格实时更新"

    if sge is Session.OPEN:
        return "Au(T+D) 正在交易，国际金已休市，价格波动通常有限"

    if intl is Session.OPEN:
        reason = {
            Session.WEEKEND: "周末",
            Session.HOLIDAY: "法定节假日",
        }.get(sge, "非交易时段")
        return (
            f"Au(T+D) 处于{reason}休市，价格为上一交易日收盘价；"
            "国际金正常交易，请以国际金走势为主要参考"
        )

    return "Au(T+D) 与国际金均已休市，价格均为上一交易日收盘价，无需过度关注"
