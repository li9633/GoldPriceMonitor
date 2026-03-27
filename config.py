
# 监控目标
SYMBOL = "gds_AUTD"  # 监控品种代码
SYMBOL_NAME_MAP = {
    "gds_AUTD": "黄金延期",
    "hf_GC": "纽约黄金",
    "hf_XAU": "伦敦金"
}

# 数据源
API_URL = "https://www.huilvbiao.com/api/gold_indexApi"

# 检查间隔（秒）
CHECK_INTERVAL = 30

# 历史数据导入配置
HISTORICAL_DATA_CONFIG = {
    "auto_import_on_start": True,  # 启动时自动导入
    "min_records_threshold": 100,  # 最少记录数阈值，低于此值则触发导入
    "periods": ["60d", "1y"]  # 导入周期
}

MESSAGE_CONFIG = {
    "include_time": True,      # 是否包含时间
    "price_format": "¥{:.2f}",  # 价格格式
    "max_conditions": 5,       # 最多显示条件数
}

SUGGESTION_CONFIG = {
    "enable_suggestions": True,   # 是否启用建议
    "suggestion_level": "medium",  # simple/medium/detailed
    "include_stop_loss": True,    # 是否包含止损建议
}

# 报警条件配置
class AlertConfig:
    # 绝对阈值报警
    ENABLE_ABSOLUTE_ALERT = True
    ABSOLUTE_LOW_PRICE = 915.0

    # 相对低点报警
    ENABLE_RELATIVE_ALERT = True
    RELATIVE_WINDOW_HOURS = 24

    # 窄幅震荡突破报警
    ENABLE_BREAKOUT_ALERT = True
    CONSOLIDATION_HOURS = 12
    VOLATILITY_THRESHOLD = 0.003  # 0.3%

    # 趋势反转报警
    ENABLE_TREND_ALERT = True

    # 波动率异常报警
    ENABLE_VOLATILITY_ALERT = True

    # 均线交叉报警
    ENABLE_MA_CROSS_ALERT = True
    MA_SHORT_PERIOD = 12  # 短期均线周期
    MA_LONG_PERIOD = 48   # 长期均线周期

    # 连续涨跌报警
    ENABLE_CONSECUTIVE_ALERT = True
    CONSECUTIVE_COUNT = 5  # 连续涨跌周期数

    # 快速涨跌报警
    ENABLE_RAPID_CHANGE_ALERT = True
    RAPID_CHANGE_THRESHOLD = 0.015  # 2% 快速变动
    RAPID_CHANGE_WINDOW_MINUTES = 30  # 检测窗口


# 企业微信机器人配置
WECHAT_WORK_CONFIG = {
    "enabled": True,  # 启用企业微信通知
    # 机器人webhook地址
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9a3f8ed0-bd6a-4123-9cff-2a1dba190971",
}

# 邮件通知配置
EMAIL_CONFIG = {
    "enabled": False,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "li9633@qq.com", # 发送者邮箱
    "sender_password": "lxzzrtlgvejyjafh",  # 授权码
    "receiver_email": "li9633@qq.com" # 接收者邮箱
}

# 数据库配置
DB_FILE = "gold_price_history.db"
