import sqlite3
from datetime import datetime

from config import MODEL_POOL_DB_FILE
from utils.logger import get_logger

logger = get_logger("AiStatsMapper")


class AiStatsMapper:
    """AI 调用统计持久化 — 存入 model_pool.db"""

    def __init__(self, db_file: str = MODEL_POOL_DB_FILE):
        self.db_file = db_file

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS ai_call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            call_time DATETIME NOT NULL,
            success INTEGER NOT NULL DEFAULT 1,
            latency_ms INTEGER,
            error_reason TEXT,
            from_cache INTEGER DEFAULT 0,
            triggered_alerts TEXT,
            raw_response TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_logs_call_time "
            "ON ai_call_logs(call_time)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_logs_success ON ai_call_logs(success)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_logs_provider "
            "ON ai_call_logs(provider_name)"
        )
        conn.commit()
        conn.close()

    def insert_log(
        self,
        provider_name: str,
        model_name: str,
        call_time: datetime,
        success: bool,
        latency_ms: int | None,
        error_reason: str | None,
        from_cache: bool,
        triggered_alerts: str | None,
        raw_response: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO ai_call_logs "
            "(provider_name, model_name, call_time, success, latency_ms, "
            "error_reason, from_cache, triggered_alerts, raw_response, "
            "prompt_tokens, completion_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                provider_name,
                model_name,
                call_time.strftime("%Y-%m-%d %H:%M:%S"),
                1 if success else 0,
                latency_ms,
                error_reason,
                1 if from_cache else 0,
                triggered_alerts,
                raw_response,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            ),
        )
        conn.commit()
        conn.close()

    # ==================== 统计查询 ====================

    def _today_where(self) -> str:
        return "date(call_time) = date('now', 'localtime')"

    def get_overview_raw(self) -> dict:
        conn = self._get_connection()
        c = conn.cursor()

        today = self._today_where()

        c.execute(f"SELECT COUNT(*) FROM ai_call_logs WHERE {today}")
        today_total = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM ai_call_logs WHERE {today} AND success=1")
        today_success = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM ai_call_logs WHERE {today} AND from_cache=1")
        today_cache = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM ai_call_logs")
        total_all = c.fetchone()[0]

        c.execute(
            "SELECT call_time FROM ai_call_logs WHERE success=1 "
            "ORDER BY call_time DESC LIMIT 1"
        )
        last_success_row = c.fetchone()
        last_success_time = last_success_row[0] if last_success_row else None

        c.execute(
            f"SELECT COALESCE(AVG(latency_ms), 0) FROM ai_call_logs WHERE {today} AND latency_ms IS NOT NULL"
        )
        avg_latency = c.fetchone()[0]

        c.execute(
            f"SELECT COUNT(*) FROM ai_call_logs WHERE {today} AND latency_ms > 30000"
        )
        timeout_count = c.fetchone()[0]

        c.execute(
            f"SELECT provider_name, model_name, COUNT(*) AS cnt "
            f"FROM ai_call_logs WHERE {today} "
            f"GROUP BY provider_name, model_name ORDER BY cnt DESC LIMIT 1"
        )
        top_model_row = c.fetchone()

        c.execute(
            f"SELECT provider_name, COUNT(*) AS cnt "
            f"FROM ai_call_logs WHERE {today} "
            f"GROUP BY provider_name ORDER BY cnt DESC LIMIT 1"
        )
        top_provider_row = c.fetchone()

        c.execute(
            f"SELECT error_reason, COUNT(*) AS cnt "
            f"FROM ai_call_logs WHERE {today} AND success=0 AND error_reason IS NOT NULL "
            f"GROUP BY error_reason ORDER BY cnt DESC LIMIT 5"
        )
        top_failures = [{"reason": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute(
            f"SELECT strftime('%H', call_time) AS hour, COUNT(*) AS cnt "
            f"FROM ai_call_logs WHERE {today} "
            f"GROUP BY hour ORDER BY hour"
        )
        hourly = [{"hour": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute(
            f"SELECT provider_name, model_name, "
            f"COUNT(*) AS total, "
            f"ROUND(100.0 * SUM(success) / COUNT(*), 1) AS success_rate, "
            f"COALESCE(AVG(latency_ms), 0) AS avg_latency "
            f"FROM ai_call_logs WHERE {today} "
            f"GROUP BY provider_name, model_name ORDER BY total DESC"
        )
        model_ranking = [
            {
                "provider": r[0],
                "model": r[1],
                "total": r[2],
                "success_rate": r[3],
                "avg_latency": r[4],
            }
            for r in c.fetchall()
        ]

        c.execute(
            f"SELECT provider_name, "
            f"COUNT(*) AS total, "
            f"ROUND(100.0 * SUM(success) / COUNT(*), 1) AS success_rate, "
            f"COALESCE(AVG(latency_ms), 0) AS avg_latency "
            f"FROM ai_call_logs WHERE {today} "
            f"GROUP BY provider_name ORDER BY total DESC"
        )
        provider_ranking = [
            {
                "provider": r[0],
                "total": r[1],
                "success_rate": r[2],
                "avg_latency": r[3],
            }
            for r in c.fetchall()
        ]

        c.execute(
            "SELECT latency_ms FROM ai_call_logs "
            f"WHERE {today} AND latency_ms IS NOT NULL "
            "ORDER BY latency_ms"
        )
        latencies = [r[0] for r in c.fetchall()]

        c.execute(
            f"SELECT provider_name, COUNT(*) AS cnt "
            f"FROM ai_call_logs WHERE {today} AND success=0 "
            f"GROUP BY provider_name ORDER BY cnt DESC"
        )
        provider_failures = [{"provider": r[0], "count": r[1]} for r in c.fetchall()]

        conn.close()

        return {
            "today_total": today_total,
            "today_success": today_success,
            "today_cache": today_cache,
            "total_all": total_all,
            "last_success_time": last_success_time,
            "avg_latency": avg_latency,
            "timeout_count": timeout_count,
            "top_model": {
                "provider": top_model_row[0],
                "model": top_model_row[1],
                "count": top_model_row[2],
            }
            if top_model_row
            else None,
            "top_provider": {
                "provider": top_provider_row[0],
                "count": top_provider_row[1],
            }
            if top_provider_row
            else None,
            "top_failures": top_failures,
            "hourly": hourly,
            "model_ranking": model_ranking,
            "provider_ranking": provider_ranking,
            "latencies": latencies,
            "provider_failures": provider_failures,
        }

    def get_consecutive_failures(self) -> int:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("SELECT success FROM ai_call_logs ORDER BY call_time DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        count = 0
        for row in rows:
            if row[0] == 0:
                count += 1
            else:
                break
        return count

    def get_daily_trend(self, days: int = 7) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT date(call_time) AS d, "
            "COUNT(*) AS total, "
            "SUM(success) AS success_count, "
            "COALESCE(AVG(latency_ms), 0) AS avg_latency "
            "FROM ai_call_logs "
            "WHERE call_time >= datetime('now', 'localtime', ?) "
            "GROUP BY d ORDER BY d",
            (f"-{days} days",),
        )
        result = [
            {
                "date": r[0],
                "total": r[1],
                "success_count": r[2],
                "avg_latency": r[3],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return result

    def get_recent_logs(self, page: int, page_size: int) -> tuple[list[dict], int]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM ai_call_logs")
        total = c.fetchone()[0]
        offset = (page - 1) * page_size
        c.execute(
            "SELECT id, provider_name, model_name, call_time, success, "
            "latency_ms, error_reason, from_cache, triggered_alerts, raw_response, "
            "prompt_tokens, completion_tokens, total_tokens "
            "FROM ai_call_logs ORDER BY call_time DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [
            {
                "id": r[0],
                "provider_name": r[1],
                "model_name": r[2],
                "call_time": r[3],
                "success": bool(r[4]),
                "latency_ms": r[5],
                "error_reason": r[6],
                "from_cache": bool(r[7]),
                "triggered_alerts": r[8],
                "raw_response": r[9],
                "prompt_tokens": r[10],
                "completion_tokens": r[11],
                "total_tokens": r[12],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows, total

    def get_token_overview(self, days: int = 1) -> dict:
        """Token 消耗概览"""
        conn = self._get_connection()
        c = conn.cursor()
        where = (
            "date(call_time) = date('now', 'localtime')"
            if days == 1
            else (f"call_time >= datetime('now', 'localtime', '-{days} days')")
        )
        c.execute(
            f"SELECT "
            f"COALESCE(SUM(prompt_tokens), 0), "
            f"COALESCE(SUM(completion_tokens), 0), "
            f"COALESCE(SUM(total_tokens), 0), "
            f"COUNT(*) AS calls "
            f"FROM ai_call_logs WHERE {where} AND success=1"
        )
        row = c.fetchone()
        conn.close()
        return {
            "prompt_tokens": row[0],
            "completion_tokens": row[1],
            "total_tokens": row[2],
            "calls": row[3],
        }

    def get_token_by_model(self, days: int = 1) -> list[dict]:
        """按模型/供应商分组的 Token 消耗"""
        conn = self._get_connection()
        c = conn.cursor()
        where = (
            "date(call_time) = date('now', 'localtime')"
            if days == 1
            else (f"call_time >= datetime('now', 'localtime', '-{days} days')")
        )
        c.execute(
            f"SELECT provider_name, model_name, "
            f"COALESCE(SUM(prompt_tokens), 0), "
            f"COALESCE(SUM(completion_tokens), 0), "
            f"COALESCE(SUM(total_tokens), 0), "
            f"COUNT(*) AS calls "
            f"FROM ai_call_logs WHERE {where} AND success=1 "
            f"GROUP BY provider_name, model_name ORDER BY total_tokens DESC"
        )
        rows = [
            {
                "provider_name": r[0],
                "model_name": r[1],
                "prompt_tokens": r[2],
                "completion_tokens": r[3],
                "total_tokens": r[4],
                "calls": r[5],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows

    def get_token_daily_trend(self, days: int = 7) -> list[dict]:
        """每日 Token 消耗趋势"""
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT date(call_time) AS d, "
            "COALESCE(SUM(prompt_tokens), 0), "
            "COALESCE(SUM(completion_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COUNT(*) AS calls "
            "FROM ai_call_logs "
            "WHERE call_time >= datetime('now', 'localtime', ?) AND success=1 "
            "GROUP BY d ORDER BY d",
            (f"-{days} days",),
        )
        rows = [
            {
                "date": r[0],
                "prompt_tokens": r[1],
                "completion_tokens": r[2],
                "total_tokens": r[3],
                "calls": r[4],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows
