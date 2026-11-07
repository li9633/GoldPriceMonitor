from config import MODEL_POOL_DB_FILE
from mapper.base import SQLiteMapper
from utils.crypto import decrypt_value, encrypt_value, is_encrypted
from utils.logger import get_logger

logger = get_logger("ModelPoolMapper")


def _decrypt_api_key(stored: str) -> str:
    """解密 API Key；历史明文存的是环境变量名（非真实 Key），改造后已失效，视为未配置。"""
    return decrypt_value(stored) if is_encrypted(stored) else ""


class ModelPoolMapper(SQLiteMapper):
    """模型池配置持久化 — 与价格数据分离，存入 model_pool.db"""

    def __init__(self, db_file: str = MODEL_POOL_DB_FILE):
        # 连接不设 row_factory —— 存量代码按元组索引取值
        super().__init__(db_file, wal=True, row_factory=False)

    def init_tables(self) -> None:
        with self._session() as conn:
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

    # ==================== 供应商 CRUD ====================

    def get_providers(self) -> list[dict]:
        with self._session() as conn:
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
                        "api_key": _decrypt_api_key(row[3]),
                        "timeout": row[4],
                        "sort_order": row[5],
                        "models": models,
                    }
                )
            return providers

    def get_provider_by_name(self, name: str) -> dict | None:
        with self._session() as conn:
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
                "api_key": _decrypt_api_key(row[3]),
                "timeout": row[4],
                "sort_order": row[5],
                "models": models,
            }

    def insert_provider(
        self, name: str, api_url: str, api_key: str, timeout: int, sort_order: int
    ) -> int:
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO model_providers (name, api_url, api_key, timeout, sort_order) VALUES (?, ?, ?, ?, ?)",
                (name, api_url, encrypt_value(api_key), timeout, sort_order),
            )
            assert c.lastrowid is not None
            return c.lastrowid

    def update_provider(self, name: str, **kwargs) -> bool:
        if not kwargs:
            return False
        if kwargs.get("api_key"):
            kwargs["api_key"] = encrypt_value(kwargs["api_key"])
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [name]
        with self._session() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE model_providers SET {fields} WHERE name=?", values)
            return c.rowcount > 0

    def delete_provider(self, name: str) -> bool:
        with self._session() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM provider_models WHERE provider_name=?", (name,))
            c.execute("DELETE FROM model_providers WHERE name=?", (name,))
            return c.rowcount > 0

    # ==================== 模型 CRUD ====================

    def get_models_by_provider(self, provider_name: str) -> list[dict]:
        with self._session() as conn:
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
        with self._session() as conn:
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
        with self._session() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO provider_models (provider_name, model_name, sort_order) VALUES (?, ?, ?)",
                (provider_name, model_name, sort_order),
            )
            assert c.lastrowid is not None
            return c.lastrowid

    def update_model(self, model_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [model_id]
        with self._session() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE provider_models SET {fields} WHERE id=?", values)
            return c.rowcount > 0

    def delete_model(self, model_id: int) -> bool:
        with self._session() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM provider_models WHERE id=?", (model_id,))
            return c.rowcount > 0

    def close(self) -> None:
        pass
