from datetime import datetime

from chinese_calendar import is_workday

from config import AUTD_TRADING_HOURS, CHINA_TZ


def is_autd_trading() -> bool:
    """判断当前是否在 Au(T+D) 交易时段内
    
    自动处理：周末、法定节假日、调休工作日
    """
    now = datetime.now(CHINA_TZ)

    # 非工作日（周末/节假日）直接返回休市
    if not is_workday(now.date()):
        return False

    current_minutes = now.hour * 60 + now.minute

    for start_str, end_str in AUTD_TRADING_HOURS:
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            if start_minutes <= current_minutes <= end_minutes:
                return True
        else:
            if current_minutes >= start_minutes or current_minutes <= end_minutes:
                return True

    return False


def get_trading_status_text() -> str:
    """获取当前交易状态描述文本，区分周末/节假日/非交易时段"""
    now = datetime.now(CHINA_TZ)

    if is_autd_trading():
        return "Au(T+D) 当前处于交易时段，价格实时更新"

    if not is_workday(now.date()):
        if now.weekday() >= 5:
            return "Au(T+D) 周末休市，伦敦金同样休市，价格均为上一个交易日收盘价，无需过度关注"
        return "Au(T+D) 法定节假日休市，伦敦金正常交易，请以伦敦金走势为主要参考"

    return "Au(T+D) 当前处于休市时段（非交易时间），伦敦金正常交易，请以伦敦金走势为主要参考"