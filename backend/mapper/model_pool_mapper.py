import sqlite3

from config import MODEL_POOL_DB_FILE


class ModelPoolMapper:
    """模型池配置持久化 — 与价格数据分离，存入 model_pool.db"""

    def __init__(self, db_file: str = MODEL_POOL_DB_FILE):
        self.db_file = db_file
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_file, check_same_thread=False)
        return self._conn

    def init_tables(self) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS model_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            api_url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            timeout INTEGER DEFAULT 30,
            sort_order INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS provider_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (provider_name) REFERENCES model_providers(name)
        )""")
        conn.commit()

    # ==================== 供应商 CRUD ====================

    def get_providers(self) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, name, api_url, api_key, timeout, sort_order FROM model_providers ORDER BY sort_order"
        )
        providers = []
        for row in c.fetchall():
            c2 = conn.cursor()
            c2.execute(
                "SELECT id, model_name, sort_order FROM provider_models WHERE provider_name=? ORDER BY sort_order",
                (row[1],),
            )
            models = [m[1] for m in c2.fetchall()]
            providers.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "api_url": row[2],
                    "api_key": row[3],
                    "timeout": row[4],
                    "sort_order": row[5],
                    "models": models,
                }
            )
        return providers

    def get_provider_by_name(self, name: str) -> dict | None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, name, api_url, api_key, timeout, sort_order FROM model_providers WHERE name=?",
            (name,),
        )
        row = c.fetchone()
        if not row:
            return None
        c2 = conn.cursor()
        c2.execute(
            "SELECT id, model_name, sort_order FROM provider_models WHERE provider_name=? ORDER BY sort_order",
            (name,),
        )
        models = [m[1] for m in c2.fetchall()]
        return {
            "id": row[0],
            "name": row[1],
            "api_url": row[2],
            "api_key": row[3],
            "timeout": row[4],
            "sort_order": row[5],
            "models": models,
        }

    def insert_provider(
        self, name: str, api_url: str, api_key: str, timeout: int, sort_order: int
    ) -> int:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO model_providers (name, api_url, api_key, timeout, sort_order) VALUES (?, ?, ?, ?, ?)",
            (name, api_url, api_key, timeout, sort_order),
        )
        conn.commit()
        assert c.lastrowid is not None
        return c.lastrowid

    def update_provider(self, name: str, **kwargs) -> bool:
        if not kwargs:
            return False
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [name]
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(f"UPDATE model_providers SET {fields} WHERE name=?", values)
        conn.commit()
        return c.rowcount > 0

    def delete_provider(self, name: str) -> bool:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM provider_models WHERE provider_name=?", (name,))
        c.execute("DELETE FROM model_providers WHERE name=?", (name,))
        conn.commit()
        return c.rowcount > 0

    # ==================== 模型 CRUD ====================

    def get_models_by_provider(self, provider_name: str) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, provider_name, model_name, sort_order FROM provider_models WHERE provider_name=? ORDER BY sort_order",
            (provider_name,),
        )
        return [
            {"id": r[0], "provider_name": r[1], "model_name": r[2], "sort_order": r[3]}
            for r in c.fetchall()
        ]

    def get_model_by_id(self, model_id: int) -> dict | None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, provider_name, model_name, sort_order FROM provider_models WHERE id=?",
            (model_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "provider_name": row[1],
            "model_name": row[2],
            "sort_order": row[3],
        }

    def insert_model(self, provider_name: str, model_name: str, sort_order: int) -> int:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO provider_models (provider_name, model_name, sort_order) VALUES (?, ?, ?)",
            (provider_name, model_name, sort_order),
        )
        conn.commit()
        assert c.lastrowid is not None
        return c.lastrowid

    def update_model(self, model_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [model_id]
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(f"UPDATE provider_models SET {fields} WHERE id=?", values)
        conn.commit()
        return c.rowcount > 0

    def delete_model(self, model_id: int) -> bool:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM provider_models WHERE id=?", (model_id,))
        conn.commit()
        return c.rowcount > 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
