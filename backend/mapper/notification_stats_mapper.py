import sqlite3
from datetime import datetime

from config import CHINA_TZ, SYSTEM_SETTINGS_DB_FILE
from utils.date_filter import build_date_filter
from utils.logger import get_logger

logger = get_logger("NotificationStatsMapper")


class NotificationStatsMapper:
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
        conn.close()

    def insert_log(
        self,
        alert_level: str,
        symbol: str,
        symbol_name: str,
        current_price: float | None,
        alert_summary: str,
        channel_type: str,
        channel_name: str,
        chain_id: str,
        chain_position: int,
        chain_total: int,
        success: bool,
        latency_ms: float | None,
        error_type: str,
        error_reason: str,
    ) -> None:
        conn = self._get_connection()
        c = conn.cursor()
        now = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO notification_send_logs "
            "(alert_level, symbol, symbol_name, current_price, alert_summary, "
            "channel_type, channel_name, chain_id, chain_position, chain_total, "
            "success, latency_ms, error_type, error_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alert_level,
                symbol,
                symbol_name,
                current_price,
                alert_summary,
                channel_type,
                channel_name,
                chain_id,
                chain_position,
                chain_total,
                1 if success else 0,
                latency_ms,
                error_type,
                error_reason,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def _date_where(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        """统一构建通知日志的日期筛选 WHERE 子句"""
        return build_date_filter(hours, start_date, end_date, "created_at", "datetime")

    def get_simple_stats(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> dict:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)

        c.execute(f"SELECT COUNT(*) FROM notification_send_logs WHERE {where}")
        total = c.fetchone()[0]

        c.execute(
            f"SELECT COUNT(*) FROM notification_send_logs WHERE {where} AND success=1"
        )
        success = c.fetchone()[0]

        conn.close()
        return {
            "total_sends": total,
            "success_count": success,
            "failure_count": total - success,
            "success_rate": round(100.0 * success / total, 1) if total else 0.0,
        }

    def get_overview(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)

        c.execute(f"SELECT COUNT(*) FROM notification_send_logs WHERE {where}")
        today_total = c.fetchone()[0]

        c.execute(
            f"SELECT COUNT(*) FROM notification_send_logs WHERE {where} AND success=1"
        )
        today_success = c.fetchone()[0]

        c.execute(
            f"SELECT COALESCE(AVG(latency_ms), 0) FROM notification_send_logs "
            f"WHERE {where} AND latency_ms IS NOT NULL"
        )
        avg_latency = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM notification_send_logs")
        total_all = c.fetchone()[0]

        conn.close()
        return {
            "today_total": today_total,
            "today_success": today_success,
            "today_failure": today_total - today_success,
            "success_rate": round(100.0 * today_success / today_total, 1)
            if today_total
            else 0.0,
            "avg_latency_ms": round(avg_latency, 1),
            "total_all": total_all,
        }

    def get_top_failures(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)
        c.execute(
            f"SELECT error_type, COUNT(*) AS fail_count, "
            f"GROUP_CONCAT(DISTINCT SUBSTR(error_reason, 1, 100)) AS examples "
            f"FROM notification_send_logs "
            f"WHERE {where} AND success=0 AND error_type != '' "
            f"GROUP BY error_type ORDER BY fail_count DESC LIMIT 5"
        )
        total_failures = sum(r[1] for r in c.fetchall())
        c.execute(
            f"SELECT error_type, COUNT(*) AS fail_count, "
            f"GROUP_CONCAT(DISTINCT SUBSTR(error_reason, 1, 100)) AS examples "
            f"FROM notification_send_logs "
            f"WHERE {where} AND success=0 AND error_type != '' "
            f"GROUP BY error_type ORDER BY fail_count DESC LIMIT 5"
        )
        result = [
            {
                "error_type": r[0],
                "fail_count": r[1],
                "percentage": round(100.0 * r[1] / total_failures, 1)
                if total_failures
                else 0.0,
                "examples": r[2] or "",
            }
            for r in c.fetchall()
        ]
        conn.close()
        return result

    def get_channel_stats(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)
        c.execute(
            f"SELECT channel_type, channel_name, COUNT(*) AS total, "
            f"SUM(success) AS success_count, "
            f"COUNT(*) - SUM(success) AS fail_count, "
            f"ROUND(100.0 * SUM(success) / COUNT(*), 1) AS success_rate, "
            f"COALESCE(AVG(latency_ms), 0) AS avg_latency "
            f"FROM notification_send_logs WHERE {where} "
            f"GROUP BY channel_type ORDER BY total DESC"
        )
        result = [
            {
                "channel_type": r[0],
                "channel_name": r[1],
                "total": r[2],
                "success_count": r[3],
                "fail_count": r[4],
                "success_rate": r[5],
                "avg_latency_ms": round(r[6], 1),
            }
            for r in c.fetchall()
        ]
        conn.close()
        return result

    def get_daily_trend(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)
        c.execute(
            f"SELECT date(created_at) AS d, "
            f"COUNT(*) AS total, "
            f"SUM(success) AS success_count, "
            f"COUNT(*) - SUM(success) AS fail_count "
            f"FROM notification_send_logs "
            f"WHERE {where} "
            f"GROUP BY d ORDER BY d"
        )
        result = [
            {"date": r[0], "total": r[1], "success_count": r[2], "fail_count": r[3]}
            for r in c.fetchall()
        ]
        conn.close()
        return result

    def get_logs(
        self,
        page: int,
        page_size: int,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[list[dict], int]:
        conn = self._get_connection()
        c = conn.cursor()
        where = self._date_where(hours, start_date, end_date)
        c.execute(f"SELECT COUNT(*) FROM notification_send_logs WHERE {where}")
        total = c.fetchone()[0]
        offset = (page - 1) * page_size
        c.execute(
            f"SELECT id, alert_level, symbol, symbol_name, current_price, "
            f"alert_summary, channel_type, channel_name, chain_id, "
            f"chain_position, chain_total, success, latency_ms, "
            f"error_type, error_reason, created_at "
            f"FROM notification_send_logs WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [
            {
                "id": r[0],
                "alert_level": r[1],
                "symbol": r[2],
                "symbol_name": r[3],
                "current_price": r[4],
                "alert_summary": r[5],
                "channel_type": r[6],
                "channel_name": r[7],
                "chain_id": r[8],
                "chain_position": r[9],
                "chain_total": r[10],
                "success": bool(r[11]),
                "latency_ms": r[12],
                "error_type": r[13],
                "error_reason": r[14],
                "created_at": r[15],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows, total

    def get_chain_detail(self, chain_id: str) -> list[dict]:
        conn = self._get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, alert_level, symbol, symbol_name, current_price, "
            "alert_summary, channel_type, channel_name, chain_id, "
            "chain_position, chain_total, success, latency_ms, "
            "error_type, error_reason, created_at "
            "FROM notification_send_logs WHERE chain_id=? "
            "ORDER BY chain_position",
            (chain_id,),
        )
        rows = [
            {
                "id": r[0],
                "alert_level": r[1],
                "symbol": r[2],
                "symbol_name": r[3],
                "current_price": r[4],
                "alert_summary": r[5],
                "channel_type": r[6],
                "channel_name": r[7],
                "chain_id": r[8],
                "chain_position": r[9],
                "chain_total": r[10],
                "success": bool(r[11]),
                "latency_ms": r[12],
                "error_type": r[13],
                "error_reason": r[14],
                "created_at": r[15],
            }
            for r in c.fetchall()
        ]
        conn.close()
        return rows
