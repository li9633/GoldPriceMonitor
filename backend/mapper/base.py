"""SQLite mapper 公共基类 —— 统一连接管理与事务上下文。

历史背景：各 mapper 曾各自复制同一套「连接 + 事务上下文」实现，且早期
个别 mapper 忘记 close 导致句柄泄漏。本基类收拢为唯一实现，子类只声明
连接参数差异（WAL / row_factory / 额外 PRAGMA）。

事务语义：`with self._session() as conn:` 正常退出 commit、异常 rollback
且**必定 close**。注意 `with sqlite3.connect(...) as conn` 只是事务上下文，
不会关闭连接，严禁直接使用。

调用点约定：统一使用 `self._session()`；`self._connect()` 是历史别名，
既有代码可继续工作，新代码请用 `_session`。
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager


class SQLiteMapper:
    """所有 SQLite mapper 的公共基类"""

    def __init__(
        self,
        db_file: str,
        *,
        wal: bool = True,
        row_factory: bool = True,
        extra_pragmas: Sequence[str] = (),
    ) -> None:
        self.db_file = db_file
        self._wal = wal
        self._row_factory = row_factory
        self._extra_pragmas = tuple(extra_pragmas)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        if self._wal:
            conn.execute("PRAGMA journal_mode=WAL")
        for pragma in self._extra_pragmas:
            conn.execute(pragma)
        if self._row_factory:
            conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """打开连接，正常退出提交、异常回滚，且必定关闭。"""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    #: 历史别名 —— advice / portfolio / price / exchange_rate 等早期
    #: mapper 的调用点用 `_connect`，保留以免逐个改写
    _connect = _session
