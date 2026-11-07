"""utils.date_filter 日期筛选 SQL 构建测试。"""
from utils.date_filter import build_date_filter


def test_hours_filter():
    assert (
        build_date_filter(hours=24)
        == "created_at >= datetime('now', 'localtime', '-24 hours')"
    )


def test_hours_filter_unixepoch():
    assert (
        build_date_filter(hours=24, time_format="unixepoch")
        == "created_at >= strftime('%s', 'now', 'localtime', '-24 hours')"
    )


def test_start_and_end_date():
    assert (
        build_date_filter(start_date="2026-01-01", end_date="2026-01-31")
        == "date(created_at) BETWEEN '2026-01-01' AND '2026-01-31'"
    )


def test_start_date_only():
    assert (
        build_date_filter(start_date="2026-01-01")
        == "date(created_at) >= '2026-01-01'"
    )


def test_end_date_only():
    assert (
        build_date_filter(end_date="2026-01-31")
        == "date(created_at) <= '2026-01-31'"
    )


def test_default_today():
    assert build_date_filter() == "date(created_at) = date('now', 'localtime')"


def test_hours_priority_over_dates():
    # hours 参数优先于日期参数
    assert (
        build_date_filter(hours=6, start_date="2026-01-01", end_date="2026-01-31")
        == "created_at >= datetime('now', 'localtime', '-6 hours')"
    )


def test_custom_time_column():
    assert (
        build_date_filter(start_date="2026-01-01", time_column="ts")
        == "date(ts) >= '2026-01-01'"
    )
