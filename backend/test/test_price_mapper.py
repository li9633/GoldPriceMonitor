"""mapper.price_mapper 价格快照统计与持久化测试。"""
from datetime import timedelta

import pytest

from mapper.price_mapper import PriceMapper, PriceSnapshot, _percentile_value
from utils.time_utils import now


class TestPercentileValue:
    def test_boundaries(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile_value(data, 0) == 1.0
        assert _percentile_value(data, 100) == 5.0
        assert _percentile_value(data, 50) == 3.0

    def test_interpolation(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile_value(data, 12.5) == pytest.approx(1.5)
        assert _percentile_value(data, 25) == 2.0

    def test_single_element(self):
        assert _percentile_value([42.0], 100) == 42.0

    def test_clamp_out_of_range(self):
        data = [1.0, 2.0, 3.0]
        assert _percentile_value(data, 200) == 3.0  # clamp 到 100
        assert _percentile_value(data, -50) == 1.0  # clamp 到 0


def _make_snapshot() -> PriceSnapshot:
    """构造 5 个递增价格点（旧→新），全部落在 24h 内。"""
    base = now()
    prices = [100.0, 101.0, 102.0, 103.0, 104.0]
    times = [base - timedelta(minutes=(4 - i)) for i in range(5)]
    return PriceSnapshot(
        list(zip(times, prices, strict=True)), list(prices), min_3m=95.0, min_6m=90.0
    )


class TestPriceSnapshot:
    def test_prices_last_n(self):
        snap = _make_snapshot()
        assert snap.prices_last_n(3) == [102.0, 103.0, 104.0]

    def test_statistics(self):
        snap = _make_snapshot()
        stats = snap.statistics(24)
        assert stats["count"] == 5
        assert stats["min"] == 100.0
        assert stats["max"] == 104.0
        assert stats["avg"] == pytest.approx(102.0)
        assert stats["std"] == pytest.approx(2**0.5)

    def test_ma(self):
        snap = _make_snapshot()
        assert snap.ma(3) == pytest.approx(103.0)

    def test_percentile_boundary(self):
        snap = _make_snapshot()
        assert snap.percentile(24, 100) == 104.0
        assert snap.percentile(24, 0) == 100.0
        assert snap.percentile(24, 50) == 102.0

    def test_trend_up(self):
        snap = _make_snapshot()
        trend = snap.trend(24)
        assert trend["direction"] == "up"
        # 递增序列线性回归斜率为正（实现用 x_mean=n/2，斜率 = 10/11.25）
        assert trend["slope"] == pytest.approx(10 / 11.25)

    def test_trend_stable(self):
        base = now()
        prices = [100.0, 100.0, 100.0]
        times = [base - timedelta(minutes=(2 - i)) for i in range(3)]
        snap = PriceSnapshot(
            list(zip(times, prices, strict=True)), list(prices), 100.0, 100.0
        )
        trend = snap.trend(24)
        assert trend["direction"] == "stable"
        assert trend["slope"] == pytest.approx(0.0)


class TestPriceMapper:
    def test_save_and_count(self, tmp_db):
        m = PriceMapper(tmp_db)
        m.save_price("gds_AUTD", 500.0)
        m.save_price("gds_AUTD", 510.0)
        assert m.get_record_count("gds_AUTD") == 2

    def test_prices_in_window(self, tmp_db):
        m = PriceMapper(tmp_db)
        m.save_price("gds_AUTD", 500.0)
        m.save_price("gds_AUTD", 510.0)
        assert sorted(m.get_prices_in_window("gds_AUTD", 24)) == [500.0, 510.0]

    def test_statistics(self, tmp_db):
        m = PriceMapper(tmp_db)
        m.save_price("gds_AUTD", 500.0)
        m.save_price("gds_AUTD", 510.0)
        stats = m.get_price_statistics("gds_AUTD", hours=24)
        assert stats["min"] == 500.0
        assert stats["max"] == 510.0
        assert stats["count"] == 2

    def test_moving_average(self, tmp_db):
        m = PriceMapper(tmp_db)
        m.save_price("gds_AUTD", 500.0)
        m.save_price("gds_AUTD", 510.0)
        assert m.get_moving_average("gds_AUTD", 2) == pytest.approx(505.0)

    def test_batch_insert_dedup(self, tmp_db):
        m = PriceMapper(tmp_db)
        dt = now()
        records = [
            ("gds_AUTD", 500.0, dt),
            ("gds_AUTD", 500.0, dt),  # 相同 symbol+timestamp，应被去重
            ("hf_XAU", 2000.0, dt),
        ]
        count = m.batch_insert_prices(records)
        assert count == 2
        assert m.get_record_count("gds_AUTD") == 1
