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
OUNCE_TO_GRAM = 31.1035

# 数据源
GOLD_PRICE_API_URL = "https://www.huilvbiao.com/api/gold_indexApi"
USD_TO_CNY_API_URL = "https://open.er-api.com/v6/latest/USD"

# 检查间隔默认值（秒），实际以 system_settings.db 中 monitor_config 为准
CHECK_INTERVAL = 10

# Au(T+D) 交易时段（上海黄金交易所，北京时间）
# 夜盘跨日：20:00 至次日 02:30
AUTD_TRADING_HOURS = [
    ("09:00", "11:30"),  # 日盘上午
    ("13:30", "15:30"),  # 日盘下午
    ("20:00", "23:59"),  # 夜盘上半段
    ("00:00", "02:30"),  # 夜盘下半段（跨日）
]

# 数据库文件路径
PRICE_HISTORY_DB_FILE = "data/prices.db"  # 价格历史数据
MODEL_POOL_DB_FILE = "data/model_pool.db"  # AI 模型池配置
SYSTEM_SETTINGS_DB_FILE = (
    "data/system_settings.db"  # 系统设置（报警 / AI / 通知 / 汇率缓存）
)
