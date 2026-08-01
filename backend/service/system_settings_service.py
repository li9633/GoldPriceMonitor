import json
import os
from typing import Self

from config import DEBUG, GOLD_PRICE_API_URL, LOG_DIR, USD_TO_CNY_API_URL
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
    def _scan_dir(dir_path: str) -> tuple[list[str], int, int]:
        """扫描目录，返回 (文件列表, 文件数, 总大小字节)"""
        files: list[str] = []
        total_size = 0
        if os.path.isdir(dir_path):
            for entry in os.scandir(dir_path):
                if entry.is_file():
                    files.append(entry.name)
                    total_size += entry.stat().st_size
        files.sort()
        return files, len(files), total_size

    @staticmethod
    def get_infrastructure_config() -> dict:
        log_files, log_file_count, log_dir_size = SystemSettingsService._scan_dir(
            LOG_DIR
        )
        db_files, db_file_count, db_dir_size = SystemSettingsService._scan_dir("data")
        return {
            "gold_price_api_url": GOLD_PRICE_API_URL,
            "usd_to_cny_api_url": USD_TO_CNY_API_URL,
            "timezone": "UTC+8",
            "debug_mode": DEBUG,
            "log_dir": LOG_DIR,
            "log_file_count": log_file_count,
            "log_files": log_files,
            "log_dir_size_bytes": log_dir_size,
            "db_dir": "data",
            "db_file_count": db_file_count,
            "db_files": db_files,
            "db_dir_size_bytes": db_dir_size,
        }

    # ==================== 通知渠道 ====================

    def get_notification_channels(self) -> list[dict]:
        return self.mapper.get_notification_channels()

    def update_notification_channel(
        self,
        channel_type: str,
        display_name: str,
        enabled: bool,
        priority: int,
        config: dict,
    ) -> None:
        self.mapper.upsert_notification_channel(
            channel_type, display_name, enabled, priority, config
        )

    def delete_notification_channel(self, channel_type: str) -> bool:
        return self.mapper.delete_notification_channel(channel_type)

    # ==================== 通知策略 ====================

    def get_notification_strategy(self) -> dict:
        row = self.mapper.get_notification_strategy()
        if row is None:
            return {"stop_on_first_success": True}
        return {k: v for k, v in row.items() if k not in ("id", "updated_at")}

    def update_notification_strategy(self, **kwargs) -> None:
        self.mapper.update_notification_strategy(**kwargs)

    # ==================== 汇率缓存 ====================

    def get_cached_exchange_rate(self) -> float | None:
        row = self.mapper.get_exchange_rate()
        return row["rate"] if row else None

    def get_exchange_rate_row(self) -> dict | None:
        return self.mapper.get_exchange_rate()

    def set_cached_exchange_rate(self, rate: float) -> None:
        self.mapper.upsert_exchange_rate(rate)
        logger.info(f"汇率已缓存至数据库：{rate}")
