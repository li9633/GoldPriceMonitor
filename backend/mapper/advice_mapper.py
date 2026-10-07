"""建议记录持久化 —— 存在 `portfolio.db`（与持仓同属业务流水，非配置）。

`advice_records` 同时承担三件事：

1. **审计**：`evidence` 冻结当时的行情与持仓，事后能回答「当时凭什么这么建议」；
2. **生命周期**：`status`（delivered → acknowledged → acted/suppressed）；
3. **有效性追踪**：`price_at_advice` + `price_t1/t7/t30`。这组数据是唯一能回答
   「我的建议准不准」的东西，所以从第一天就要存 —— 后补代价极大。

所有查询走 `_connect()`，退出时提交并**必定关闭**连接。
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from config import PORTFOLIO_DB_FILE
from models.advice import AdviceStatus
from utils.logger import get_logger
from utils.time_utils import now, now_str

logger = get_logger("AdviceMapper")

#: 允许写入的列
_COLUMNS = (
    "created_at",
    "kind",
    "action",
    "symbol",
    "target_grams",
    "price_band_low",
    "price_band_high",
    "confidence",
    "rationale",
    "signals",
    "evidence",
    "model_info",
    "status",
    "suppressed_reason",
    "acted_lot_id",
    "price_at_advice",
    "subject_lot_id",
    "review_horizon",
)

#: JSON 序列化的列
_JSON_COLUMNS = ("signals", "evidence")

#: 有效性回访档位
REVIEW_HORIZONS = (1, 7, 30)


class AdviceMapper:
    """建议记录的读写"""

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
            c.execute("""CREATE TABLE IF NOT EXISTS advice_records (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at        TEXT    NOT NULL,
                kind              TEXT    NOT NULL,
                action            TEXT    NOT NULL,
                symbol            TEXT    NOT NULL,
                target_grams      REAL    NULL,
                price_band_low    REAL    NULL,
                price_band_high   REAL    NULL,
                confidence        REAL    DEFAULT 0.5,
                rationale         TEXT    NOT NULL DEFAULT '',
                signals           TEXT    NOT NULL DEFAULT '[]',
                evidence          TEXT    NOT NULL DEFAULT '{}',
                model_info        TEXT    NOT NULL DEFAULT '',
                status            TEXT    NOT NULL DEFAULT 'delivered',
                suppressed_reason TEXT    NOT NULL DEFAULT '',
                acted_lot_id      INTEGER NULL,
                price_at_advice   REAL    NULL,
                price_t1          REAL    NULL,
                price_t7          REAL    NULL,
                price_t30         REAL    NULL,
                reviewed_at       TEXT    NULL,
                subject_lot_id    INTEGER NULL,
                review_horizon    INTEGER NULL
            )""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_advice_created "
                "ON advice_records(created_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_advice_symbol "
                "ON advice_records(symbol, created_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_advice_status "
                "ON advice_records(status)"
            )
            self._migrate_columns(c)

    @staticmethod
    def _migrate_columns(c: sqlite3.Cursor) -> None:
        """老库补列"""
        existing = {row[1] for row in c.execute("PRAGMA table_info(advice_records)")}
        for column, ddl in (
            ("subject_lot_id", "INTEGER NULL"),
            ("review_horizon", "INTEGER NULL"),
        ):
            if column not in existing:
                c.execute(f"ALTER TABLE advice_records ADD COLUMN {column} {ddl}")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_advice_subject_lot "
            "ON advice_records(subject_lot_id, review_horizon)"
        )

    # ==================== 写 ====================

    def insert_advice(self, data: dict) -> int:
        payload: dict = {"created_at": data.get("created_at") or now_str()}
        for key in _COLUMNS:
            if key == "created_at":
                continue
            value = data.get(key)
            if key in _JSON_COLUMNS:
                fallback: list | dict = [] if key == "signals" else {}
                value = json.dumps(
                    value if value is not None else fallback, ensure_ascii=False
                )
            # 值为 None 的列直接省略，让建表语句里的 DEFAULT 生效
            if value is not None:
                payload[key] = value
        columns = ", ".join(payload)
        placeholders = ", ".join(["?"] * len(payload))
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"INSERT INTO advice_records ({columns}) VALUES ({placeholders})",
                tuple(payload.values()),
            )
            return int(c.lastrowid or 0)

    def update_status(
        self,
        advice_id: int,
        status: str,
        acted_lot_id: int | None = None,
        suppressed_reason: str | None = None,
    ) -> bool:
        with self._connect() as conn:
            c = conn.cursor()
            sets = ["status = ?"]
            params: list[object] = [status]
            if acted_lot_id is not None:
                sets.append("acted_lot_id = ?")
                params.append(acted_lot_id)
            if suppressed_reason is not None:
                sets.append("suppressed_reason = ?")
                params.append(suppressed_reason)
            params.append(advice_id)
            c.execute(
                f"UPDATE advice_records SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            return c.rowcount > 0

    def update_review_prices(
        self, advice_id: int, column: str, price: float
    ) -> bool:
        if column not in {f"price_t{h}" for h in REVIEW_HORIZONS}:
            raise ValueError(f"不支持的回访档位：{column}")
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f"UPDATE advice_records SET {column} = ?, reviewed_at = ? "
                "WHERE id = ? AND "
                f"{column} IS NULL",
                (price, now_str(), advice_id),
            )
            return c.rowcount > 0

    # ==================== 读 ====================

    def get_advice(self, advice_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM advice_records WHERE id = ?", (advice_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list_advice(
        self,
        symbol: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._where_sql(symbol, kind, status)
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM advice_records{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def count_advice(
        self,
        symbol: str | None = None,
        kind: str | None = None,
        status: str | None = None,
    ) -> int:
        where, params = self._where_sql(symbol, kind, status)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM advice_records{where}", params
            ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _where_sql(
        symbol: str | None, kind: str | None, status: str | None
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def last_pushed(self, symbol: str) -> dict | None:
        """最近一条**真正推送过**的建议（排除被抑制的）。

        监控循环用它判断「这次还值不值得再推一条」—— 用数据库而不是内存，
        这样重启之后不会立刻重复推送。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM advice_records WHERE symbol = ? AND status != ? "
                "ORDER BY id DESC LIMIT 1",
                (symbol, AdviceStatus.SUPPRESSED.value),
            ).fetchone()
        return self._row(row) if row else None

    def has_review(self, lot_id: int, horizon: int) -> bool:
        """该笔买入的 T+N 复盘是否已经生成过。

        只认**非 suppressed** 的记录：被闸门拦下的复盘意味着用户没收到，
        应当在下一次巡检（仍在追补窗口内）重试，而不是永远丢失。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM advice_records WHERE subject_lot_id = ? "
                "AND review_horizon = ? AND status != ? LIMIT 1",
                (lot_id, horizon, AdviceStatus.SUPPRESSED.value),
            ).fetchone()
        return row is not None

    def list_reviews_for_lot(self, lot_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM advice_records WHERE subject_lot_id = ? "
                "ORDER BY review_horizon ASC",
                (lot_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_pending_reviews(
        self, horizon_days: int, at: datetime | None = None
    ) -> list[dict]:
        """某档位已到期但还没回填价格的记录。

        `horizon_days` 取 1 / 7 / 30；到期判定用 `created_at <= at - N 天`。
        `at` 可注入，便于测试与补跑。
        """
        if horizon_days not in REVIEW_HORIZONS:
            raise ValueError(f"不支持的回访档位：{horizon_days}")
        column = f"price_t{horizon_days}"
        reference = at or now()
        cutoff = (reference - timedelta(days=horizon_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        sql = (
            f"SELECT * FROM advice_records WHERE {column} IS NULL "
            "AND price_at_advice IS NOT NULL AND created_at <= ? "
            "ORDER BY id ASC LIMIT 500"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, (cutoff,)).fetchall()
        return [self._row(row) for row in rows]

    def review_stats(self) -> dict:
        """建议有效性汇总：各档位的样本量与平均价格变动（%）"""
        stats: dict = {}
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM advice_records").fetchone()[0]
            for horizon in REVIEW_HORIZONS:
                column = f"price_t{horizon}"
                row = conn.execute(
                    f"SELECT COUNT(*), AVG(({column} - price_at_advice) "
                    f"/ price_at_advice * 100) FROM advice_records "
                    f"WHERE {column} IS NOT NULL AND price_at_advice > 0"
                ).fetchone()
                stats[f"with_t{horizon}"] = int(row[0] or 0)
                stats[f"avg_move_t{horizon}_pct"] = (
                    None if row[1] is None else round(float(row[1]), 3)
                )
        stats["total"] = int(total or 0)
        return stats

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        data = dict(row)
        for column, fallback in (("signals", []), ("evidence", {})):
            raw = data.get(column)
            try:
                data[column] = json.loads(raw) if raw else fallback
            except json.JSONDecodeError:
                logger.warning("建议 %s 的 %s 不是合法 JSON", data.get("id"), column)
                data[column] = fallback
        return data
