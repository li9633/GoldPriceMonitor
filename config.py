# config.py
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
CHECK_INTERVAL = 300

# 报警条件配置


class AlertConfig:
    # 绝对阈值报警
    ENABLE_ABSOLUTE_ALERT = True
    ABSOLUTE_LOW_PRICE = 980.0

    # 相对低点报警
    ENABLE_RELATIVE_ALERT = True
    RELATIVE_WINDOW_HOURS = 24

    # 窄幅震荡突破报警 (可选)
    ENABLE_BREAKOUT_ALERT = False
    CONSOLIDATION_HOURS = 12
    VOLATILITY_THRESHOLD = 0.005  # 0.5%


# 邮件通知配置
EMAIL_CONFIG = {
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "your_email@qq.com",
    "sender_password": "your_authorization_code",  # 注意是授权码
    "receiver_email": "receiver@email.com"
}

# 数据库配置
DB_FILE = "gold_price_history.db"
