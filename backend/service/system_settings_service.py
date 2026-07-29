import json
from typing import Self

from config import GOLD_PRICE_API_URL, LOG_DIR, USD_TO_CNY_API_URL
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
        json_fields_with_defaults = {
            "periods": ["60d", "1y"],
            "monitor_symbols": ["gds_AUTD", "hf_XAU"],
            "trading_hours": [
                ["09:00", "11:30"],
                ["13:30", "15:30"],
                ["20:00", "23:59"],
                ["00:00", "02:30"],
            ],
        }
        for field, default in json_fields_with_defaults.items():
            if field in result and isinstance(result[field], str):
                try:
                    result[field] = json.loads(result[field])
                except json.JSONDecodeError:
                    result[field] = default
        return result

    def update_monitor_config(self, **kwargs) -> None:
        clean = dict(kwargs)
        json_fields = ["periods", "monitor_symbols", "trading_hours"]
        for field in json_fields:
            if field in clean and isinstance(clean[field], list):
                clean[field] = json.dumps(clean[field])
        self.mapper.update_monitor_config(**clean)

    # ==================== 消息模板 ====================

    def get_message_config(self) -> dict:
        row = self.mapper.get_message_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_message_config(self, **kwargs) -> None:
        self.mapper.update_message_config(**kwargs)

    # ==================== 品种名称映射 ====================

    def get_symbol_config(self) -> list[dict]:
        return self.mapper.get_symbol_config()

    def get_symbol_name_map(self) -> dict[str, str]:
        return self.mapper.get_symbol_name_map()

    def upsert_symbol(
        self, symbol: str, display_name: str, sort_order: int = 0
    ) -> None:
        self.mapper.upsert_symbol(symbol, display_name, sort_order)

    def delete_symbol(self, symbol: str) -> bool:
        return self.mapper.delete_symbol(symbol)

    # ==================== 日志配置 ====================

    def get_log_config(self) -> dict:
        row = self.mapper.get_log_config()
        if row is None:
            return {}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_log_config(self, **kwargs) -> None:
        self.mapper.update_log_config(**kwargs)

    # ==================== 基础设施配置（只读） ====================

    @staticmethod
    def get_infrastructure_config() -> dict:
        return {
            "gold_price_api_url": GOLD_PRICE_API_URL,
            "usd_to_cny_api_url": USD_TO_CNY_API_URL,
            "timezone": "UTC+8",
            "log_dir": LOG_DIR,
        }

    # ==================== 汇率缓存 ====================

    def get_cached_exchange_rate(self) -> float | None:
        row = self.mapper.get_exchange_rate()
        return row["rate"] if row else None

    def set_cached_exchange_rate(self, rate: float) -> None:
        self.mapper.upsert_exchange_rate(rate)
        logger.info(f"汇率已缓存至数据库：{rate}")
