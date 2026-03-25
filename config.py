
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

# 报警条件配置


class AlertConfig:
    # 绝对阈值报警
    ENABLE_ABSOLUTE_ALERT = True
    ABSOLUTE_LOW_PRICE = 915.0

    # 相对低点报警
    ENABLE_RELATIVE_ALERT = True
    RELATIVE_WINDOW_HOURS = 24

    # 窄幅震荡突破报警 (可选)
    ENABLE_BREAKOUT_ALERT = False
    CONSOLIDATION_HOURS = 12
    VOLATILITY_THRESHOLD = 0.005  # 0.5%


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
