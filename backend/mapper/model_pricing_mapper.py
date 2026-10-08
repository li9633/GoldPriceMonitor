
from config import MODEL_POOL_DB_FILE
from mapper.base import SQLiteMapper
from utils.time_utils import now_str


class ModelPricingMapper(SQLiteMapper):
    def __init__(self, db_file: str = MODEL_POOL_DB_FILE):
        super().__init__(db_file, wal=True, row_factory=True)

    def init_table(self) -> None:
        with self._session() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS model_pricing (
                id INTEGER PRIMARY KEY,
                provider_name TEXT NOT NULL,
                model_name TEXT NOT NULL,
                input_price REAL NOT NULL DEFAULT 0,
                output_price REAL NOT NULL DEFAULT 0,
                currency TEXT DEFAULT 'CNY',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(provider_name, model_name)
            )""")
            conn.commit()

    def list_all(self) -> list[dict]:
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, provider_name, model_name, input_price, output_price, "
                "currency, updated_at FROM model_pricing ORDER BY provider_name, model_name"
            )
            rows = [dict(r) for r in c.fetchall()]
        return rows

    def get_by_provider_model(self, provider_name: str, model_name: str) -> dict | None:
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, provider_name, model_name, input_price, output_price, "
                "currency, updated_at FROM model_pricing "
                "WHERE provider_name=? AND model_name=?",
                (provider_name, model_name),
            )
            row = c.fetchone()
        return dict(row) if row else None

    def upsert(
        self,
        provider_name: str,
        model_name: str,
        input_price: float,
        output_price: float,
        currency: str = "CNY",
    ) -> int:
        now = now_str()
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO model_pricing "
                "(provider_name, model_name, input_price, output_price, currency, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(provider_name, model_name) DO UPDATE SET "
                "input_price=excluded.input_price, output_price=excluded.output_price, "
                "currency=excluded.currency, updated_at=excluded.updated_at",
                (provider_name, model_name, input_price, output_price, currency, now),
            )
            conn.commit()
            row_id = c.lastrowid
        return row_id or 0

    def update(self, pricing_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        kwargs["updated_at"] = now_str()
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [pricing_id]
        with self._session() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE model_pricing SET {fields} WHERE id=?", values)
            conn.commit()
            affected = c.rowcount > 0
        return affected

    def delete(self, pricing_id: int) -> bool:
        with self._session() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM model_pricing WHERE id=?", (pricing_id,))
            conn.commit()
            affected = c.rowcount > 0
        return affected

    def get_by_provider_model_list(
        self, keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], dict]:
        """批量查询定价，key 为 (provider_name, model_name)"""
        if not keys:
            return {}
        with self._session() as conn:
            c = conn.cursor()
            placeholders = ", ".join("(?, ?)" for _ in keys)
            flat = [v for k in keys for v in k]
            c.execute(
                "SELECT provider_name, model_name, input_price, output_price, currency "
                f"FROM model_pricing WHERE (provider_name, model_name) IN ({placeholders})",
                flat,
            )
            result = {}
            for r in c.fetchall():
                result[(r[0], r[1])] = {
                    "input_price": r[2],
                    "output_price": r[3],
                    "currency": r[4],
                }
        return result
