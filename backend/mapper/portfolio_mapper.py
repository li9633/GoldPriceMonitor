"""持仓与购买计划的持久化 — 独立存入 `portfolio.db`。

与 `system_settings.db` 分开：那张库里的表都是覆盖式配置（固定 `id=1`），
而这里是追加式流水。

所有查询都走 `_connect()` 上下文管理器 —— 它退出时提交并必定关闭连接。
不要用 `with sqlite3.connect(...) as conn`，那只是事务上下文，不会关闭连接。
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from config import PORTFOLIO_DB_FILE
from utils.logger import get_logger
from utils.time_utils import now_str

logger = get_logger("PortfolioMapper")

#: 允许写入的列，避免把任意字段名拼进 SQL
_LOT_COLUMNS = (
    "symbol",
    "trade_date",
    "grams",
    "price_per_gram",
    "fee",
    "channel",
    "plan_id",
    "note",
    "is_opening",
)
_PLAN_COLUMNS = (
    "symbol",
    "target_grams",
    "budget",
    "tranches",
    "tranche_grams",
    "trigger_policy",
    "start_date",
    "end_date",
    "status",
)
_SALE_COLUMNS = (
    "symbol",
    "sale_date",
    "grams",
    "price_per_gram",
    "fee",
    "channel",
    "note",
)

#: 与建表语句里的 DEFAULT 保持一致。
#: INSERT 会显式列出每一列，因此不能依赖 DDL 的默认值 —— 缺失的字段必须在这里补齐，
#: 否则会撞上 NOT NULL 约束。
_LOT_DEFAULTS: dict[str, object] = {
    "fee": 0.0,
    "channel": "",
    "note": "",
    "plan_id": None,
    # 0 = 正常买入；1 = 期初持仓
    "is_opening": 0,
}
_PLAN_DEFAULTS: dict[str, object] = {
    "budget": None,
    "tranches": 1,
    "tranche_grams": None,
    "start_date": None,
    "end_date": None,
    "status": "active",
}
_SALE_DEFAULTS: dict[str, object] = {"fee": 0.0, "channel": "", "note": ""}


def _pick(data: dict, columns: tuple[str, ...], defaults: dict) -> dict:
    """按列取値，缺失或为 None 时回落到默认值（显式传 0 / "" 则保留）"""
    picked = {}
    for key in columns:
        value = data.get(key)
        picked[key] = defaults.get(key) if value is None else value
    return picked


class PortfolioMapper:
    """买入批次 + 购买计划"""

    def __init__(self, db_file: str = PORTFOLIO_DB_FILE):
        self.db_file = db_file
        self.init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接，退出时提交并**关闭**"""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_tables(self) -> None:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS purchase_lots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                trade_date      TEXT    NOT NULL,
                grams           REAL    NOT NULL,
                price_per_gram  REAL    NOT NULL,
                fee             REAL    NOT NULL DEFAULT 0,
                channel         TEXT    NOT NULL DEFAULT '',
                plan_id         INTEGER NULL,
                note            TEXT    NOT NULL DEFAULT '',
                is_opening      INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS purchase_plans (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                target_grams    REAL    NOT NULL,
                budget          REAL    NULL,
                tranches        INTEGER NOT NULL DEFAULT 1,
                tranche_grams   REAL    NULL,
                trigger_policy  TEXT    NOT NULL DEFAULT '{}',
                start_date      TEXT    NULL,
                end_date        TEXT    NULL,
                status          TEXT    NOT NULL DEFAULT 'active',
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            )""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_lots_symbol_date "
                "ON purchase_lots(symbol, trade_date)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_lots_plan ON purchase_lots(plan_id)"
            )
            c.execute("""CREATE TABLE IF NOT EXISTS sale_records (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                sale_date       TEXT    NOT NULL,
                grams           REAL    NOT NULL,
                price_per_gram  REAL    NOT NULL,
                fee             REAL    NOT NULL DEFAULT 0,
                channel         TEXT    NOT NULL DEFAULT '',
                note            TEXT    NOT NULL DEFAULT '',
                created_at      TEXT    NOT NULL
            )""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_symbol_date "
                "ON sale_records(symbol, sale_date)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_symbol_status "
                "ON purchase_plans(symbol, status)"
            )
            self._migrate_columns(c)

    @staticmethod
    def _migrate_columns(c: sqlite3.Cursor) -> None:
        """老库补列"""
        existing = {row[1] for row in c.execute("PRAGMA table_info(purchase_lots)")}
        if "is_opening" not in existing:
            c.execute(
                "ALTER TABLE purchase_lots ADD COLUMN is_opening INTEGER NOT NULL DEFAULT 0"
            )

    # ==================== 买入批次 ====================

    def list_lots(self, symbol: str | None = None) -> list[dict]:
        """按买入日期正序返回流水（账本顺序）"""
        sql = "SELECT * FROM purchase_lots"
        params: tuple = ()
        if symbol:
            sql += " WHERE symbol = ?"
            params = (symbol,)
        sql += " ORDER BY trade_date ASC, id ASC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def get_lot(self, lot_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM purchase_lots WHERE id = ?", (lot_id,)
            ).fetchone()
        return dict(row) if row else None

    def insert_lot(self, data: dict) -> int:
        payload = _pick(data, _LOT_COLUMNS, _LOT_DEFAULTS)
        payload["created_at"] = now_str()
        columns = ", ".join(payload)
        placeholders = ", ".join(["?"] * len(payload))
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"INSERT INTO purchase_lots ({columns}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
            return int(c.lastrowid or 0)

    def update_lot(self, lot_id: int, data: dict) -> bool:
        fields = {
            key: value for key, value in data.items() if key in _LOT_COLUMNS
        }
        if not fields:
            return self.get_lot(lot_id) is not None
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = (*fields.values(), lot_id)
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"UPDATE purchase_lots SET {assignments} WHERE id = ?", params
            )
            return c.rowcount > 0

    def delete_lot(self, lot_id: int) -> bool:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM purchase_lots WHERE id = ?", (lot_id,))
            return c.rowcount > 0

    def delete_lots_by_plan(self, plan_id: int) -> int:
        """删除某计划下的所有批次（仅用于测试与级联清理）"""
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM purchase_lots WHERE plan_id = ?", (plan_id,))
            return c.rowcount

    # ==================== 卖出记录 ====================

    def list_sales(self, symbol: str | None = None) -> list[dict]:
        """按卖出日期正序返回流水（账本顺序）"""
        sql = "SELECT * FROM sale_records"
        params: tuple = ()
        if symbol:
            sql += " WHERE symbol = ?"
            params = (symbol,)
        sql += " ORDER BY sale_date ASC, id ASC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def get_sale(self, sale_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sale_records WHERE id = ?", (sale_id,)
            ).fetchone()
        return dict(row) if row else None

    def insert_sale(self, data: dict) -> int:
        payload = _pick(data, _SALE_COLUMNS, _SALE_DEFAULTS)
        payload["created_at"] = now_str()
        columns = ", ".join(payload)
        placeholders = ", ".join(["?"] * len(payload))
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"INSERT INTO sale_records ({columns}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
            return int(c.lastrowid or 0)

    def update_sale(self, sale_id: int, data: dict) -> bool:
        fields = {key: value for key, value in data.items() if key in _SALE_COLUMNS}
        if not fields:
            return self.get_sale(sale_id) is not None
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = (*fields.values(), sale_id)
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE sale_records SET {assignments} WHERE id = ?", params)
            return c.rowcount > 0

    def delete_sale(self, sale_id: int) -> bool:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM sale_records WHERE id = ?", (sale_id,))
            return c.rowcount > 0

    # ==================== 购买计划 ====================

    def list_plans(
        self, symbol: str | None = None, status: str | None = None
    ) -> list[dict]:
        clauses = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status:
            clauses.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM purchase_plans"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        with self._connect() as conn:
            return [self._plan_row(row) for row in conn.execute(sql, params).fetchall()]

    def get_plan(self, plan_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM purchase_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return self._plan_row(row) if row else None

    def insert_plan(self, data: dict) -> int:
        payload = _pick(data, _PLAN_COLUMNS, _PLAN_DEFAULTS)
        payload["trigger_policy"] = json.dumps(
            data.get("trigger_policy") or {}, ensure_ascii=False
        )
        timestamp = now_str()
        payload["created_at"] = timestamp
        payload["updated_at"] = timestamp
        columns = ", ".join(payload)
        placeholders = ", ".join(["?"] * len(payload))
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"INSERT INTO purchase_plans ({columns}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
            return int(c.lastrowid or 0)

    def update_plan(self, plan_id: int, data: dict) -> bool:
        fields = {key: value for key, value in data.items() if key in _PLAN_COLUMNS}
        if "trigger_policy" in fields:
            fields["trigger_policy"] = json.dumps(
                fields["trigger_policy"] or {}, ensure_ascii=False
            )
        if not fields:
            return self.get_plan(plan_id) is not None
        fields["updated_at"] = now_str()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = (*fields.values(), plan_id)
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE purchase_plans SET {assignments} WHERE id = ?", params)
            return c.rowcount > 0

    def delete_plan(self, plan_id: int) -> bool:
        """删除计划，并把关联批次的 `plan_id` 置空（不删买入记录）"""
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE purchase_lots SET plan_id = NULL WHERE plan_id = ?", (plan_id,)
            )
            c.execute("DELETE FROM purchase_plans WHERE id = ?", (plan_id,))
            return c.rowcount > 0

    @staticmethod
    def _plan_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        raw = data.get("trigger_policy") or "{}"
        try:
            data["trigger_policy"] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("计划 %s 的 trigger_policy 不是合法 JSON，已按空处理", data.get("id"))
            data["trigger_policy"] = {}
        return data
