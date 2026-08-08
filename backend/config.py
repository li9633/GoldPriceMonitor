import os

# ==================== 基础设施常量（不可迁移） ====================

# 运行模式：通过环境变量 GOLD_MONITOR_DEBUG 控制（true=开发模式，false=生产模式）
# Windows: set GOLD_MONITOR_DEBUG=true
# Linux/Mac: export GOLD_MONITOR_DEBUG=true
DEBUG = os.getenv("GOLD_MONITOR_DEBUG", "false").lower() == "true"

# 日志目录（logger 初始化时确定，运行时不可变）
LOG_DIR = "logs"

# 数据源 API URL（前端只读展示，更改需同步修改解析逻辑）
GOLD_PRICE_API_URL = "https://www.huilvbiao.com/api/gold_indexApi"

# 数据库文件路径
PRICE_HISTORY_DB_FILE = "data/prices.db"  # 价格历史数据
MODEL_POOL_DB_FILE = "data/model_pool.db"  # AI 模型池配置
SYSTEM_SETTINGS_DB_FILE = "data/system_settings.db"  # 系统设置（报警 / AI / 通知 / 汇率缓存 / 监控 / 品种 / 日志）
