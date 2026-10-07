"""在线节假日结果缓存 —— 落库到 data/calendar.db。

只缓存**在线源**的判定（贵且不稳定，必须复用）；lib 与 weekly 的判定
不落库（本地、零成本）。缓存不设过期：节假日安排一经公布不会回改。
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from utils.logger import get_logger
from utils.time_utils import now_str

logger = get_logger("CalendarCache")

_CALENDAR_DB_FILE = "data/calendar.db"


class CalendarCacheMapper:
    def __init__(self, db_file: str = _CALENDAR_DB_FILE):
        self.db_file = db_file
        self._ensure_dir()
        self.init_tables()

    def _ensure_dir(self) -> None:
        import os

        parent = os.path.dirname(self.db_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """事务上下文：退出时 commit/rollback 且必定 close（防连接泄漏）"""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_tables(self) -> None:
        with self._session() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS holiday_cache (
                day TEXT PRIMARY KEY,
                verdict TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )"""
            )

    #: 缓存里允许出现的判定值；脏值（手工编辑/旧版本写入）一律自愈清除
    _VALID_VERDICTS = ("holiday", "workday")

    def get(self, day: date) -> str | None:
        """返回缓存的判定（'holiday' / 'workday'），无记录返回 None。

        脏值直接删除并返回 None（回退在线源重新判定），避免
        `CalendarVerdict(脏值)` 在查询链路上每轮抛异常打崩主循环。
        """
        with self._session() as conn:
            row = conn.execute(
                "SELECT verdict FROM holiday_cache WHERE day = ?",
                (day.isoformat(),),
            ).fetchone()
        verdict = row["verdict"] if row else None
        if verdict is not None and verdict not in self._VALID_VERDICTS:
            logger.error(
                f"holiday_cache 存在脏值，已清除 day={day.isoformat()} "
                f"verdict={verdict!r}"
            )
            self.delete(day)
            return None
        return verdict

    def delete(self, day: date) -> None:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM holiday_cache WHERE day = ?", (day.isoformat(),)
            )

    def put(self, day: date, verdict: str, source: str) -> None:
        with self._session() as conn:
            conn.execute(
                """INSERT INTO holiday_cache (day, verdict, source, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    verdict = excluded.verdict,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at""",
                (day.isoformat(), verdict, source, now_str()),
            )

    def count(self) -> int:
        with self._session() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM holiday_cache").fetchone()
        return int(row["n"]) if row else 0
