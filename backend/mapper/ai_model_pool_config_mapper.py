import sqlite3

from config import AI_PROVIDERS, MODEL_POOL_DB_FILE


class AIModelPoolConfigMapper:
    """AI 模型池配置持久化 — 与价格数据分离，存入 model_pool.db"""

    def __init__(self, db_file: str = MODEL_POOL_DB_FILE):
        self.db_file = db_file
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_file)
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

    def seed_defaults(self) -> None:
        if self.get_providers():
            return

        conn = self._get_connection()
        c = conn.cursor()
        for i, p in enumerate(AI_PROVIDERS):
            c.execute(
                "INSERT INTO model_providers (name, api_url, api_key, timeout, sort_order) VALUES (?, ?, ?, ?, ?)",
                (p["name"], p["api_url"], p["api_key"], p.get("timeout", 30), i),
            )
            for j, model in enumerate(p["models"]):
                c.execute(
                    "INSERT INTO provider_models (provider_name, model_name, sort_order) VALUES (?, ?, ?)",
                    (p["name"], model, j),
                )
        conn.commit()

    def get_providers(self) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT name, api_url, api_key, timeout FROM model_providers ORDER BY sort_order"
        )
        providers = []
        for name, api_url, api_key, timeout in c.fetchall():
            c2 = conn.cursor()
            c2.execute(
                "SELECT model_name FROM provider_models WHERE provider_name=? ORDER BY sort_order",
                (name,),
            )
            models = [m[0] for m in c2.fetchall()]
            providers.append(
                {
                    "name": name,
                    "api_url": api_url,
                    "api_key": api_key,
                    "models": models,
                    "timeout": timeout,
                }
            )
        return providers

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
