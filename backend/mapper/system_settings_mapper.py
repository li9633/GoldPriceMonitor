import json
import sqlite3

from config import SYSTEM_SETTINGS_DB_FILE
from utils.logger import get_logger
from utils.time_utils import now_str


def _apply_log_level_if_changed(kwargs: dict) -> None:
    if "log_level" in kwargs:
        try:
            from utils.logger import apply_log_level

            apply_log_level(kwargs["log_level"])
        except ImportError:
            pass


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
            check_interval_minutes INTEGER DEFAULT 5,
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
            main_symbol TEXT DEFAULT 'gds_AUTD',
            monitor_symbols TEXT DEFAULT '["gds_AUTD","hf_XAU"]',
            trading_hours TEXT DEFAULT '[["09:00","11:30"],["13:30","15:30"],["20:00","23:59"],["00:00","02:30"]]',
            ounce_to_gram REAL DEFAULT 31.1035,
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
        c.execute("""CREATE TABLE IF NOT EXISTS symbol_config (
            symbol TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS log_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            max_bytes INTEGER DEFAULT 10485760,
            backup_count INTEGER DEFAULT 5,
            compress_backup INTEGER DEFAULT 1,
            console_output INTEGER DEFAULT 1,
            keep_days INTEGER DEFAULT 30,
            log_level TEXT DEFAULT 'DEBUG',
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        conn.commit()
        self._ensure_default_rows(conn)
        self._migrate_monitor_config(conn)
        self._migrate_log_config(conn)
        self._migrate_ai_config(conn)
        self._seed_symbol_config(conn)
        self._init_notification_stats(conn)
        self._init_notification_channels(conn)
        self._init_notification_strategy(conn)
        conn.close()

    def _init_notification_channels(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS notification_channels (
            channel_type TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 100,
            config TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        conn.commit()
        self._seed_notification_channels(conn)

    def _init_notification_strategy(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS notification_strategy (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            stop_on_first_success INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute("INSERT OR IGNORE INTO notification_strategy (id) VALUES (1)")
        conn.commit()

    def _seed_notification_channels(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        defaults = [
            ("wechat", "企业微信", 1, 10, '{"webhook_url": ""}'),
            (
                "email",
                "邮件通知",
                1,
                30,
                '{"smtp_server": "smtp.qq.com", "smtp_port": 587, "sender_email": "", "sender_password": "", "receiver_email": ""}',
            ),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO notification_channels (channel_type, display_name, enabled, priority, config) VALUES (?, ?, ?, ?, ?)",
            defaults,
        )
        conn.commit()

    def _init_notification_stats(self, conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS notification_send_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_level     TEXT NOT NULL DEFAULT 'warning',
            symbol          TEXT NOT NULL,
            symbol_name     TEXT DEFAULT '',
            current_price   REAL,
            alert_summary   TEXT DEFAULT '',
            channel_type    TEXT NOT NULL,
            channel_name    TEXT DEFAULT '',
            chain_id        TEXT DEFAULT '',
            chain_position  INTEGER DEFAULT 0,
            chain_total     INTEGER DEFAULT 1,
            success         INTEGER NOT NULL DEFAULT 0,
            latency_ms      REAL,
            error_type      TEXT DEFAULT '',
            error_reason    TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now', 'localtime'))
        )""")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_created_at "
            "ON notification_send_logs(created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_channel "
            "ON notification_send_logs(channel_type)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_success "
            "ON notification_send_logs(success)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_error_type "
            "ON notification_send_logs(error_type)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notify_logs_chain_id "
            "ON notification_send_logs(chain_id)"
        )
        conn.commit()

    def _ensure_default_rows(self, conn: sqlite3.Connection | None = None) -> None:
        own = conn is None
        if own:
            conn = self._get_connection()
        c = conn.cursor()
        for table in [
            "alert_config",
            "ai_config",
            "wechat_config",
            "email_config",
            "monitor_config",
            "message_config",
            "log_config",
        ]:
            c.execute(f"INSERT OR IGNORE INTO {table} (id) VALUES (1)")
        conn.commit()
        if own:
            conn.close()

    def _migrate_ai_config(self, conn: sqlite3.Connection | None = None) -> None:
        new_columns = {"check_interval_minutes": "INTEGER DEFAULT 5"}
        own = conn is None
        if own:
            conn = self._get_connection()
        c = conn.cursor()
        existing = {row[1] for row in c.execute("PRAGMA table_info(ai_config)")}
        for col_name, col_def in new_columns.items():
            if col_name not in existing:
                try:
                    c.execute(f"ALTER TABLE ai_config ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()
        if own:
            conn.close()

    def _migrate_log_config(self, conn: sqlite3.Connection | None = None) -> None:
        new_columns = {"log_level": "TEXT DEFAULT 'DEBUG'"}
        own = conn is None
        if own:
            conn = self._get_connection()
        c = conn.cursor()
        existing = {row[1] for row in c.execute("PRAGMA table_info(log_config)")}
        for col_name, col_def in new_columns.items():
            if col_name not in existing:
                try:
                    c.execute(f"ALTER TABLE log_config ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()
        if own:
            conn.close()

    def _migrate_monitor_config(self, conn: sqlite3.Connection | None = None) -> None:
        """为旧版 monitor_config 表补充新增列"""
        new_columns = {
            "main_symbol": "TEXT DEFAULT 'gds_AUTD'",
            "monitor_symbols": 'TEXT DEFAULT \'["gds_AUTD","hf_XAU"]\'',
            "trading_hours": 'TEXT DEFAULT \'[["09:00","11:30"],["13:30","15:30"],["20:00","23:59"],["00:00","02:30"]]\'',
            "ounce_to_gram": "REAL DEFAULT 31.1035",
        }
        own = conn is None
        if own:
            conn = self._get_connection()
        c = conn.cursor()
        existing = {row[1] for row in c.execute("PRAGMA table_info(monitor_config)")}
        for col_name, col_def in new_columns.items():
            if col_name not in existing:
                try:
                    c.execute(
                        f"ALTER TABLE monitor_config ADD COLUMN {col_name} {col_def}"
                    )
                except sqlite3.OperationalError:
                    pass
        conn.commit()
        if own:
            conn.close()

    def _seed_symbol_config(self, conn: sqlite3.Connection | None = None) -> None:
        """初始化品种名称映射默认数据"""
        own = conn is None
        if own:
            conn = self._get_connection()
        c = conn.cursor()
        defaults = [
            ("gds_AUTD", "黄金延期", 1),
            ("hf_XAU", "伦敦金", 2),
            ("hf_GC", "纽约黄金", 3),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO symbol_config (symbol, display_name, sort_order) VALUES (?, ?, ?)",
            defaults,
        )
        conn.commit()
        if own:
            conn.close()

    # ==================== 通用 Upsert/Query ====================

    def _upsert(self, table: str, columns: list[str], values: list) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = now_str()
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

    def get_monitor_config(self) -> dict | None:
        return self._get_row("monitor_config")

    def update_monitor_config(self, **kwargs) -> None:
        self._upsert("monitor_config", list(kwargs.keys()), list(kwargs.values()))

    def get_message_config(self) -> dict | None:
        return self._get_row("message_config")

    def update_message_config(self, **kwargs) -> None:
        self._upsert("message_config", list(kwargs.keys()), list(kwargs.values()))

    # ==================== 品种名称映射 ====================

    def get_symbol_config(self) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT symbol, display_name, sort_order FROM symbol_config ORDER BY sort_order"
        )
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_symbol_name_map(self) -> dict[str, str]:
        rows = self.get_symbol_config()
        return {r["symbol"]: r["display_name"] for r in rows}

    def upsert_symbol(
        self, symbol: str, display_name: str, sort_order: int = 0
    ) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = now_str()
        c.execute(
            "INSERT INTO symbol_config (symbol, display_name, sort_order, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET display_name=excluded.display_name, sort_order=excluded.sort_order, updated_at=excluded.updated_at",
            (symbol, display_name, sort_order, now),
        )
        conn.commit()
        conn.close()

    def delete_symbol(self, symbol: str) -> bool:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM symbol_config WHERE symbol=?", (symbol,))
        conn.commit()
        affected = c.rowcount
        conn.close()
        return affected > 0

    # ==================== 日志配置 ====================

    def get_log_config(self) -> dict | None:
        return self._get_row("log_config")

    def update_log_config(self, **kwargs) -> None:
        self._upsert("log_config", list(kwargs.keys()), list(kwargs.values()))
        _apply_log_level_if_changed(kwargs)

    # ==================== 汇率缓存 ====================

    def get_exchange_rate(self) -> dict | None:
        return self._get_row("exchange_rate_cache")

    # ==================== 通知渠道 ====================

    def get_notification_channels(self) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT channel_type, display_name, enabled, priority, config "
            "FROM notification_channels ORDER BY priority"
        )
        rows = c.fetchall()
        conn.close()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["config"] = json.loads(item["config"])
            except json.JSONDecodeError:
                item["config"] = {}
            item["enabled"] = bool(item["enabled"])
            result.append(item)
        return result

    def upsert_notification_channel(
        self,
        channel_type: str,
        display_name: str,
        enabled: bool,
        priority: int,
        config: dict,
    ) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = now_str()
        c.execute(
            "INSERT INTO notification_channels (channel_type, display_name, enabled, priority, config, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(channel_type) DO UPDATE SET "
            "display_name=excluded.display_name, enabled=excluded.enabled, "
            "priority=excluded.priority, config=excluded.config, updated_at=excluded.updated_at",
            (
                channel_type,
                display_name,
                1 if enabled else 0,
                priority,
                json.dumps(config),
                now,
            ),
        )
        conn.commit()
        conn.close()

    def delete_notification_channel(self, channel_type: str) -> bool:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "DELETE FROM notification_channels WHERE channel_type=?", (channel_type,)
        )
        conn.commit()
        affected = c.rowcount
        conn.close()
        return affected > 0

    # ==================== 通知策略 ====================

    def get_notification_strategy(self) -> dict | None:
        return self._get_row("notification_strategy")

    def update_notification_strategy(self, **kwargs) -> None:
        self._upsert(
            "notification_strategy", list(kwargs.keys()), list(kwargs.values())
        )
