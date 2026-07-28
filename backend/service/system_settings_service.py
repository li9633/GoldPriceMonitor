import json
from typing import Self

from mapper.system_settings_mapper import SystemSettingsMapper
from utils.logger import get_logger

logger = get_logger("SystemSettings")


class SystemSettingsService:
    """系统设置单例服务 — 内存缓存 + 分表存取"""

    _instance: Self | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.mapper = SystemSettingsMapper()
        self.mapper.init_tables()
        self._initialized = True

    def reload(self) -> None:
        logger.info("系统设置缓存已刷新")

    # ==================== 报警配置 ====================

    def get_alert_config(self) -> dict:
        row = self.mapper.get_alert_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_alert_config(self, **kwargs) -> None:
        self.mapper.update_alert_config(**kwargs)

    # ==================== AI 配置 ====================

    def get_ai_config(self) -> dict:
        row = self.mapper.get_ai_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_ai_config(self, **kwargs) -> None:
        self.mapper.update_ai_config(**kwargs)

    # ==================== 企业微信 ====================

    def get_wechat_config(self) -> dict:
        row = self.mapper.get_wechat_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_wechat_config(self, **kwargs) -> None:
        self.mapper.update_wechat_config(**kwargs)

    # ==================== 邮件 ====================

    def get_email_config(self) -> dict:
        row = self.mapper.get_email_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_email_config(self, **kwargs) -> None:
        self.mapper.update_email_config(**kwargs)

    # ==================== 监控配置 ====================

    def get_monitor_config(self) -> dict:
        row = self.mapper.get_monitor_config()
        if row is None:
            return {}
        result = {k: v for k, v in row.items() if k not in ("id", "updated_at")}
        if "periods" in result and isinstance(result["periods"], str):
            try:
                result["periods"] = json.loads(result["periods"])
            except json.JSONDecodeError:
                result["periods"] = ["60d", "1y"]
        return result

    def update_monitor_config(self, **kwargs) -> None:
        clean = dict(kwargs)
        if "periods" in clean and isinstance(clean["periods"], list):
            clean["periods"] = json.dumps(clean["periods"])
        self.mapper.update_monitor_config(**clean)

    # ==================== 消息模板 ====================

    def get_message_config(self) -> dict:
        row = self.mapper.get_message_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_message_config(self, **kwargs) -> None:
        self.mapper.update_message_config(**kwargs)

    # ==================== 汇率缓存 ====================

    def get_cached_exchange_rate(self) -> float | None:
        row = self.mapper.get_exchange_rate()
        return row["rate"] if row else None

    def set_cached_exchange_rate(self, rate: float) -> None:
        self.mapper.upsert_exchange_rate(rate)
        logger.info(f"汇率已缓存至数据库：{rate}")
