import os
from datetime import timedelta, timezone

# 日志配置

# 统一时区：UTC+8（北京时间）
CHINA_TZ = timezone(timedelta(hours=8))

# 运行模式：通过环境变量 GOLD_MONITOR_DEBUG 控制（true=开发模式，false=生产模式）
# Windows: set GOLD_MONITOR_DEBUG=true
# Linux/Mac: export GOLD_MONITOR_DEBUG=true
DEBUG = os.getenv("GOLD_MONITOR_DEBUG", "false").lower() == "true"

LOG_CONFIG = {
    "log_dir": "logs",  # 日志目录
    "max_bytes": 10 * 1024 * 1024,  # 单个文件最大 10MB
    "backup_count": 5,  # 保留 5 个备份文件
    "compress_backup": True,  # 是否压缩备份
    "console_output": True,  # 是否输出到控制台
    "keep_days": 30,  # 日志保留天数
}

# 监控目标
SYMBOL = "gds_AUTD"  # 监控品种代码
MONITOR_SYMBOLS = ["gds_AUTD", "hf_XAU"]
SYMBOL_NAME_MAP = {"gds_AUTD": "黄金延期", "hf_GC": "纽约黄金", "hf_XAU": "伦敦金"}
USD_TO_CNY_RATE = 6.830
OUNCE_TO_GRAM = 31.1035

# 数据源
GOLD_PRICE_API_URL = "https://www.huilvbiao.com/api/gold_indexApi"

USD_TO_CNY_API_URL = "https://wise.com/zh-cn/currency-converter/usd-to-cny-rate"

# 检查间隔（秒）
CHECK_INTERVAL = 10

# Au(T+D) 交易时段（上海黄金交易所，北京时间）
# 夜盘跨日：20:00 至次日 02:30
AUTD_TRADING_HOURS = [
    ("09:00", "11:30"),  # 日盘上午
    ("13:30", "15:30"),  # 日盘下午
    ("20:00", "23:59"),  # 夜盘上半段
    ("00:00", "02:30"),  # 夜盘下半段（跨日）
]

# 历史数据导入配置
HISTORICAL_DATA_CONFIG = {
    "auto_import_on_start": True,  # 启动时自动导入
    "min_records_threshold": 100,  # 最少记录数阈值，低于此值则触发导入
    "periods": ["60d", "1y"],  # 导入周期
}

MESSAGE_CONFIG = {
    "include_time": True,  # 是否包含时间
    "price_format": "¥{:.2f}",  # 价格格式
    "max_conditions": 5,  # 最多显示条件数
}

SUGGESTION_CONFIG = {
    "enable_suggestions": True,  # 是否启用建议
    "suggestion_level": "medium",  # simple/medium/detailed
    "include_stop_loss": True,  # 是否包含止损建议
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
    MA_LONG_PERIOD = 48  # 长期均线周期

    # 连续涨跌报警
    ENABLE_CONSECUTIVE_ALERT = True
    CONSECUTIVE_COUNT = 5  # 连续涨跌周期数

    # 快速涨跌报警
    ENABLE_RAPID_CHANGE_ALERT = True
    RAPID_CHANGE_THRESHOLD = 0.015  # 2% 快速变动
    RAPID_CHANGE_WINDOW_MINUTES = 30  # 检测窗口

    ENABLE_LONG_TERM_LOW_ALERT = True  # 是否启用长期最低价警报


# 企业微信机器人配置
WECHAT_WORK_CONFIG = {
    "enabled": True,  # 启用企业微信通知
    # 机器人webhook地址
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9a3f8ed0-bd6a-4123-9cff-2a1dba190971",
}

# 邮件通知配置
EMAIL_CONFIG = {
    "enabled": True,
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "sender_email": "li9633@qq.com",  # 发送者邮箱
    "sender_password": "lxzzrtlgvejyjafh",  # 授权码
    "receiver_email": "li9633@qq.com",  # 接收者邮箱
}

# 数据库配置
DB_FILE = "gold_price_history.db"

# AI 模型供应商池（按优先级排列，L2→L3 依次降级）
# 添加新供应商：在列表末尾追加一个 dict，含 name/api_url/api_key/models
AI_PROVIDERS = [
    {
        "name": "智谱",
        "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key": os.getenv("GLM_API_KEY", ""),
        "models": [
            "glm-4.7-flash",  # L2: 优先
            "glm-4-flash",  # L2: 降级
            "glm-4-flash-250414",  # L3: 最后
        ],
        "timeout": 30,
    },
    {
        "name": "硅基流动",
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": os.getenv("SILICONFLOW_API_KEY", ""),
        "models": ["Qwen/Qwen3-8B", "THUDM/GLM-4-9B-0414", "THUDM/GLM-Z1-9B-0414"],
        "timeout": 30,
    },
    {
        "name": "NVIDIA NIM",
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key": os.getenv("NVIDIA_API_KEY", ""),
        "models": [
            "deepseek-ai/deepseek-v4-flash",
            "deepseek-ai/deepseek-v4-pro",
            "z-ai/glm-5.2",
            "qwen/qwen3-next-80b-a3b-instruct",
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
        ],
        "timeout": 30,
    },
]

# AI 全局配置
AI_CONFIG = {
    "enabled": True,
    "temperature": 0.3,
    "max_tokens": 4096,
    "check_interval_checks": 30,  # 每 N 次检查调用一次 AI
    "max_retries": 2,  # L1: 单模型最大重试次数
    "retry_base_delay": 0.5,  # L1: 指数退避基础延迟（秒）
    "cache_ttl_minutes": 60,  # L4: 缓存有效期（分钟）
}
