"""回归测试：mapper 查询不得泄漏 SQLite 连接。

背景
----
`with sqlite3.connect(...) as conn:` 只是**事务**上下文：成功时 commit、异常时
rollback，**不会关闭连接**。price_mapper.py 与 exchange_rate_mapper.py 曾用它包住
所有查询，于是每次首页仪表盘请求（GET /api/prices/dashboard）都会泄漏约 2 个
连接。每个连接会带上一份页缓存（price_mapper 设了 cache_size = -8000，即 8 MiB）
和一个文件句柄，并且要等到循环 GC 碰巧回收才会释放 —— 表现为内存随请求量阶梯式
上涨（实测 200 次请求：38 MB → 最高 590 MB、句柄 143 → 515），所以看起来
“有概率”泄漏。

修复方式：两个 mapper 增加 `_connect()` 上下文管理器，退出时 commit/rollback
并**必定 close()**，所有查询改用它。

运行
----
    cd backend
    python -m test.test_sqlite_connections

也可以直接被 pytest 收集。
"""

import gc
import os
import sqlite3
import tempfile

from mapper.exchange_rate_mapper import ExchangeRateMapper
from mapper.price_mapper import PriceMapper


def _open_connections() -> int:
    """当前仍然存活且仍然持有打开句柄的连接数（不主动触发 gc.collect）。"""
    count = 0
    for obj in gc.get_objects():
        if type(obj) is sqlite3.Connection:
            try:
                obj.execute("SELECT 1")
                count += 1
            except sqlite3.Error:
                pass  # 已关闭
    return count


def _exercise_price_mapper(mapper: PriceMapper) -> None:
    symbol = "TEST_SYMBOL"
    mapper.get_record_count(symbol)
    mapper.table_exists()
    mapper.get_prices_in_window(symbol, 24)
    mapper.get_check_snapshot(symbol)
    mapper.get_price_statistics(symbol, hours=24)
    mapper.get_moving_average(symbol, 5)
    mapper.get_price_trend(symbol, hours=24)
    mapper.get_percentile(symbol, 24, 50)
    mapper.get_price_series(symbol, 24)
    mapper.get_chart_series(symbol, hours=24)
    mapper.get_dashboard_data(hours=24)
    mapper.save_price(symbol, 100.0)


def _exercise_exchange_rate_mapper(mapper: ExchangeRateMapper) -> None:
    mapper.get_record_count()
    mapper.get_latest_rate()
    mapper.get_statistics(hours=24)
    mapper.get_trend(hours=24)
    mapper.get_chart_series(hours=24)
    mapper.get_recent_records()
    mapper.get_dashboard_data(hours=24)
    mapper.save_rate(7.0, source="test", provider="test")


def test_mappers_do_not_leak_connections() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        price_mapper = PriceMapper(db_file=os.path.join(tmp, "prices.db"))
        rate_mapper = ExchangeRateMapper(db_file=os.path.join(tmp, "rates.db"))

        # 预热：让一次性的导入/建表开销落在基线之前
        _exercise_price_mapper(price_mapper)
        _exercise_exchange_rate_mapper(rate_mapper)
        baseline = _open_connections()

        for _ in range(25):
            _exercise_price_mapper(price_mapper)
            _exercise_exchange_rate_mapper(rate_mapper)

        leaked = _open_connections() - baseline
        assert leaked <= 1, (
            f"mapper 调用后仍残留 {leaked} 个未关闭的 SQLite 连接；"
            "请确认不再使用 `with self._get_connection() as conn:`"
        )


def test_writes_are_committed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "prices.db")
        mapper = PriceMapper(db_file=db)
        mapper.save_price("COMMIT_CHECK", 1234.5)

        # 用一条全新连接读取，确认数据真的落盘而不是只留在未提交的事务里
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT price FROM prices WHERE symbol = ?", ("COMMIT_CHECK",)
            ).fetchall()
        finally:
            conn.close()
        assert rows == [(1234.5,)]


def test_failure_path_rolls_back_and_closes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "prices.db")
        mapper = PriceMapper(db_file=db)

        try:
            with mapper._connect() as conn:
                conn.execute(
                    "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
                    ("ROLLBACK_CHECK", 1.0, 1),
                )
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert mapper.get_record_count("ROLLBACK_CHECK") == 0, "异常时未回滚"

        # 连接已关闭 => Windows 上可以删除该文件
        os.remove(db)


if __name__ == "__main__":
    tests = [
        test_mappers_do_not_leak_connections,
        test_writes_are_committed,
        test_failure_path_rolls_back_and_closes,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    raise SystemExit(1 if failed else 0)
