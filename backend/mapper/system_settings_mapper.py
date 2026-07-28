import sqlite3
from datetime import datetime

from config import CHINA_TZ, SYSTEM_SETTINGS_DB_FILE
from utils.logger import get_logger

logger = get_logger("SystemSettingsMapper")


class SystemSettingsMapper:
    """系统设置持久化 — 存入 system_settings.db"""

    def __init__(self, db_file: str = SYSTEM_SETTINGS_DB_FILE):
        self.db_file = db_file

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS alert_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enable_absolute_alert INTEGER DEFAULT 1,
            absolute_low_price REAL DEFAULT 915.0,
            enable_relative_alert INTEGER DEFAULT 1,
            relative_window_hours INTEGER DEFAULT 24,
            enable_breakout_alert INTEGER DEFAULT 1,
            consolidation_hours INTEGER DEFAULT 12,
            volatility_threshold REAL DEFAULT 0.003,
            enable_trend_alert INTEGER DEFAULT 1,
            enable_volatility_alert INTEGER DEFAULT 1,
            enable_ma_cross_alert INTEGER DEFAULT 1,
            ma_short_period INTEGER DEFAULT 12,
            ma_long_period INTEGER DEFAULT 48,
            enable_consecutive_alert INTEGER DEFAULT 1,
            consecutive_count INTEGER DEFAULT 5,
            enable_rapid_change_alert INTEGER DEFAULT 1,
            rapid_change_threshold REAL DEFAULT 0.015,
            rapid_change_window_minutes INTEGER DEFAULT 30,
            enable_long_term_low_alert INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS ai_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 1,
            prompt_check INTEGER DEFAULT 0,
            temperature REAL DEFAULT 0.3,
            max_tokens INTEGER DEFAULT 4096,
            check_interval_checks INTEGER DEFAULT 30,
            max_retries INTEGER DEFAULT 2,
            retry_base_delay REAL DEFAULT 0.5,
            cache_ttl_minutes INTEGER DEFAULT 60,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS wechat_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 1,
            webhook_url TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS email_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 1,
            smtp_server TEXT DEFAULT 'smtp.qq.com',
            smtp_port INTEGER DEFAULT 587,
            sender_email TEXT DEFAULT '',
            sender_password TEXT DEFAULT '',
            receiver_email TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS monitor_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            check_interval INTEGER DEFAULT 10,
            auto_import_on_start INTEGER DEFAULT 1,
            min_records_threshold INTEGER DEFAULT 100,
            periods TEXT DEFAULT '["60d","1y"]',
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS message_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            include_time INTEGER DEFAULT 1,
            price_format TEXT DEFAULT '¥{:.2f}',
            max_conditions INTEGER DEFAULT 5,
            enable_suggestions INTEGER DEFAULT 1,
            suggestion_level TEXT DEFAULT 'medium',
            include_stop_loss INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS exchange_rate_cache (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            rate REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        conn.commit()
        conn.close()
        self._ensure_default_rows()

    def _ensure_default_rows(self) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        for table in [
            "alert_config",
            "ai_config",
            "wechat_config",
            "email_config",
            "monitor_config",
            "message_config",
        ]:
            c.execute(f"INSERT OR IGNORE INTO {table} (id) VALUES (1)")
        conn.commit()
        conn.close()

    # ==================== 通用 Upsert/Query ====================

    def _upsert(self, table: str, columns: list[str], values: list) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ", ".join([f"{col}=?" for col in columns])
        params = list(values) + [now] + list(values)
        c.execute(
            f"INSERT INTO {table} (id, {', '.join(columns)}, updated_at) "
            f"VALUES (1, {', '.join(['?'] * len(columns))}, ?) "
            f"ON CONFLICT(id) DO UPDATE SET {placeholders}, updated_at=excluded.updated_at",
            params,
        )
        conn.commit()
        conn.close()

    def _get_row(self, table: str) -> dict | None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(f"SELECT * FROM {table} WHERE id=1")
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    # ==================== 各表便捷方法 ====================

    def get_alert_config(self) -> dict | None:
        return self._get_row("alert_config")

    def update_alert_config(self, **kwargs) -> None:
        self._upsert("alert_config", list(kwargs.keys()), list(kwargs.values()))

    def get_ai_config(self) -> dict | None:
        return self._get_row("ai_config")

    def update_ai_config(self, **kwargs) -> None:
        self._upsert("ai_config", list(kwargs.keys()), list(kwargs.values()))

    def get_wechat_config(self) -> dict | None:
        return self._get_row("wechat_config")

    def update_wechat_config(self, **kwargs) -> None:
        self._upsert("wechat_config", list(kwargs.keys()), list(kwargs.values()))

    def get_email_config(self) -> dict | None:
        return self._get_row("email_config")

    def update_email_config(self, **kwargs) -> None:
        self._upsert("email_config", list(kwargs.keys()), list(kwargs.values()))

    def get_monitor_config(self) -> dict | None:
        return self._get_row("monitor_config")

    def update_monitor_config(self, **kwargs) -> None:
        self._upsert("monitor_config", list(kwargs.keys()), list(kwargs.values()))

    def get_message_config(self) -> dict | None:
        return self._get_row("message_config")

    def update_message_config(self, **kwargs) -> None:
        self._upsert("message_config", list(kwargs.keys()), list(kwargs.values()))

    def get_exchange_rate(self) -> dict | None:
        return self._get_row("exchange_rate_cache")

    def upsert_exchange_rate(self, rate: float) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO exchange_rate_cache (id, rate, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET rate=excluded.rate, updated_at=excluded.updated_at",
            (rate, now),
        )
        conn.commit()
        conn.close()
