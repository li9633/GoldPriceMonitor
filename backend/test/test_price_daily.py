"""日线聚合表（prices_daily）的一致性回归测试。

预聚合最怕的不是慢，而是**静默不一致**：点位写了、聚合没写，
或者聚合被重复累加。这些错误不会报错，只会让「3 个月低位」「总记录数」
「一年均价」慢慢变成错的数字，而且很难发现。

因此这里不测「快不快」，只死守一条不变量：
    prices_daily 的 SUM(sample_count) / MIN(low) / SUM(price_sum)
    必须与 prices 原始表在同样的时间口径下完全一致。
"""

import sqlite3
from datetime import timedelta

import pytest

from mapper.price_mapper import PriceMapper, _day_bucket
from utils.time_utils import now

SYMBOL = "gds_AUTD"


def _raw_conn(db):
    return sqlite3.connect(db)


def _assert_daily_matches_raw(db):
    conn = _raw_conn(db)
    try:
        raw = dict(
            conn.execute("SELECT symbol, COUNT(*) FROM prices GROUP BY symbol").fetchall()
        )
        daily = dict(
            conn.execute(
                "SELECT symbol, SUM(sample_count) FROM prices_daily GROUP BY symbol"
            ).fetchall()
        )
        assert daily == raw, f"日线计数与原始表不一致：daily={daily} raw={raw}"

        raw_sum = dict(
            conn.execute("SELECT symbol, SUM(price) FROM prices GROUP BY symbol").fetchall()
        )
        daily_sum = dict(
            conn.execute(
                "SELECT symbol, SUM(price_sum) FROM prices_daily GROUP BY symbol"
            ).fetchall()
        )
        for symbol, value in raw_sum.items():
            assert daily_sum[symbol] == pytest.approx(value), f"{symbol} 价格和不一致"

        raw_range = dict(
            conn.execute(
                "SELECT symbol, MIN(price) FROM prices GROUP BY symbol"
            ).fetchall()
        )
        daily_range = dict(
            conn.execute(
                "SELECT symbol, MIN(low) FROM prices_daily GROUP BY symbol"
            ).fetchall()
        )
        for symbol, value in raw_range.items():
            assert daily_range[symbol] == pytest.approx(value), f"{symbol} 最低价不一致"
    finally:
        conn.close()


def _seed_raw(mapper, points):
    """绕过 save_price 直接写原始表，模拟「老库已有数据、日线表还不存在」"""
    conn = _raw_conn(mapper.db_file)
    try:
        conn.executemany(
            "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
            [(SYMBOL, price, ts) for ts, price in points],
        )
        conn.commit()
    finally:
        conn.close()
    mapper.rebuild_daily(
        min(ts for ts, _ in points), max(ts for ts, _ in points)
    )


class TestDailyConsistency:
    def test_save_prices_keeps_daily_in_sync(self, tmp_db):
        m = PriceMapper(tmp_db)
        m.save_prices([(SYMBOL, 500.0), ("hf_XAU", 2000.0)])
        m.save_price(SYMBOL, 510.0)
        _assert_daily_matches_raw(tmp_db)

    def test_save_prices_is_one_transaction(self, tmp_db):
        """一次调用写入的多个品种必须一起可见（同一事务）"""
        m = PriceMapper(tmp_db)
        m.save_prices([(SYMBOL, 500.0), ("hf_XAU", 2000.0)])
        conn = _raw_conn(tmp_db)
        try:
            rows = conn.execute(
                "SELECT symbol FROM prices ORDER BY symbol"
            ).fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == [SYMBOL, "hf_XAU"]

    def test_batch_insert_updates_daily(self, tmp_db):
        m = PriceMapper(tmp_db)
        base = now()
        records = [
            (SYMBOL, 500.0, base),
            (SYMBOL, 505.0, base + timedelta(minutes=1)),
            (SYMBOL, 500.0, base),  # 重复，应被忽略且不计入聚合
            ("hf_XAU", 2000.0, base),
        ]
        inserted = m.batch_insert_prices(records)
        assert inserted == 3
        _assert_daily_matches_raw(tmp_db)

    def test_rebuild_is_idempotent(self, tmp_db):
        m = PriceMapper(tmp_db)
        base = now()
        _seed_raw(
            m,
            [(int((base - timedelta(days=d)).timestamp()), 600.0 + d) for d in range(5)],
        )
        conn = _raw_conn(tmp_db)
        try:
            before = conn.execute(
                "SELECT day, high, low, price_sum, sample_count FROM prices_daily ORDER BY day"
            ).fetchall()
        finally:
            conn.close()

        m.rebuild_daily(
            int((base - timedelta(days=5)).timestamp()), int(base.timestamp())
        )
        conn = _raw_conn(tmp_db)
        try:
            after = conn.execute(
                "SELECT day, high, low, price_sum, sample_count FROM prices_daily ORDER BY day"
            ).fetchall()
        finally:
            conn.close()
        assert before == after, "重复重算不应改变聚合结果"

    def test_startup_backfills_existing_database(self, tmp_db):
        """老库升级路径：只有 prices、没有 prices_daily，启动时应自动补齐"""
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "CREATE TABLE prices (id INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL, "
            "symbol TEXT, price REAL)"
        )
        base = now()
        points = [
            (int((base - timedelta(days=d, minutes=m)).timestamp()), 600.0 + d + m / 60)
            for d in range(400)
            for m in range(0, 60, 15)
        ]
        conn.executemany(
            "INSERT INTO prices (symbol, price, timestamp) VALUES (?, ?, ?)",
            [(SYMBOL, price, ts) for ts, price in points],
        )
        conn.commit()
        conn.close()

        m = PriceMapper(tmp_db)  # init_table → _sync_daily_on_startup

        conn = sqlite3.connect(tmp_db)
        try:
            daily_rows = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
        finally:
            conn.close()
        assert daily_rows > 0, "启动时未补建日线聚合"
        _assert_daily_matches_raw(tmp_db)
        assert m.get_record_count(SYMBOL) == len(points)


class TestSnapshotUsesDaily:
    def test_min_3m_and_6m_match_raw(self, tmp_db):
        m = PriceMapper(tmp_db)
        base = now()
        # 让各时间点价格互不相同，便于断言边界
        points = [
            (int((base - timedelta(hours=1)).timestamp()), 600.0),
            (int((base - timedelta(days=30)).timestamp()), 550.0),
            (int((base - timedelta(days=60)).timestamp()), 540.0),
            (int((base - timedelta(days=120)).timestamp()), 500.0),
            (int((base - timedelta(days=200)).timestamp()), 480.0),
        ]
        _seed_raw(m, points)

        snap = m.get_check_snapshot(SYMBOL)
        assert snap is not None
        assert snap.min_3m == pytest.approx(540.0)
        assert snap.min_6m == pytest.approx(500.0)

    def test_falls_back_when_daily_is_missing(self, tmp_db):
        """日线表被人为清空时，必须回退原始表而不是静默返回 None"""
        m = PriceMapper(tmp_db)
        base = now()
        _seed_raw(
            m,
            [
                (int((base - timedelta(hours=1)).timestamp()), 600.0),
                (int((base - timedelta(days=10)).timestamp()), 520.0),
            ],
        )
        conn = _raw_conn(tmp_db)
        try:
            conn.execute("DELETE FROM prices_daily")
            conn.commit()
        finally:
            conn.close()

        snap = m.get_check_snapshot(SYMBOL)
        assert snap is not None
        assert snap.min_3m == pytest.approx(520.0), "回退路径没有返回最低价"


class TestDashboardAndChart:
    def test_dashboard_total_matches_raw(self, tmp_db):
        m = PriceMapper(tmp_db)
        base = now()
        points = [
            (int((base - timedelta(days=d)).timestamp()), 600.0 + d) for d in range(10)
        ]
        _seed_raw(m, points)

        data = m.get_dashboard_data(hours=24)
        assert data["total_records"] == len(points)
        symbol_row = next(item for item in data["symbols"] if item["symbol"] == SYMBOL)
        assert symbol_row["count"] == len(points)

    def test_long_chart_reads_daily(self, tmp_db):
        m = PriceMapper(tmp_db)
        base = now()
        points = [
            (int((base - timedelta(days=d)).timestamp()), 600.0 + d) for d in range(200)
        ]
        _seed_raw(m, points)

        series = m.get_chart_series(SYMBOL, hours=8760)
        assert len(series) == len(points), "长跨度图表应一天一个点"
        # 每天一个采样时，日均价就等于当天那个价格
        by_day = {_day_bucket(ts): price for ts, price in points}
        for bucket, avg in series:
            assert avg == pytest.approx(by_day[_day_bucket(bucket.timestamp())])

    def test_short_chart_still_uses_raw_ticks(self, tmp_db):
        """24 小时内的分时曲线不能被日线表降级成一天一个点"""
        m = PriceMapper(tmp_db)
        base = now()
        points = [
            (int((base - timedelta(minutes=30 * i)).timestamp()), 600.0 + i)
            for i in range(20)
        ]
        _seed_raw(m, points)

        series = m.get_chart_series(SYMBOL, hours=24)
        assert len(series) == len(points)
