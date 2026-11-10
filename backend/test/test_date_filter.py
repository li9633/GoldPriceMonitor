"""utils.date_filter 日期筛选 SQL 构建测试。

注意：文本时间列一律生成「半开区间」而不是 `date(col) = ...`。
把列包进函数会让索引失效（200k 行的统计查询退化为全表扫描），
所以这里断言的是区间形式本身 —— 它同时保证了可索引性。
"""
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
    assert build_date_filter(start_date="2026-01-01", end_date="2026-01-31") == (
        "created_at >= '2026-01-01' AND created_at < date('2026-01-31', '+1 day')"
    )


def test_start_date_only():
    assert build_date_filter(start_date="2026-01-01") == "created_at >= '2026-01-01'"


def test_end_date_only():
    assert (
        build_date_filter(end_date="2026-01-31")
        == "created_at < date('2026-01-31', '+1 day')"
    )


def test_default_today():
    assert build_date_filter() == (
        "created_at >= date('now', 'localtime') "
        "AND created_at < date('now', 'localtime', '+1 day')"
    )


def test_hours_priority_over_dates():
    # hours 参数优先于日期参数
    assert (
        build_date_filter(hours=6, start_date="2026-01-01", end_date="2026-01-31")
        == "created_at >= datetime('now', 'localtime', '-6 hours')"
    )


def test_custom_time_column():
    assert build_date_filter(start_date="2026-01-01", time_column="ts") == (
        "ts >= '2026-01-01'"
    )


def test_text_column_is_never_wrapped_in_function():
    """回归：文本时间列的每个分支都不得把列包进 date()/strftime()。

    这正是本次性能修复防住的退化 —— 一旦包裹，索引失效，统计接口
    会从毫秒级退回全表扫描。
    """
    cases = [
        build_date_filter(),
        build_date_filter(start_date="2026-01-01"),
        build_date_filter(end_date="2026-01-31"),
        build_date_filter(start_date="2026-01-01", end_date="2026-01-31"),
        build_date_filter(hours=12),
    ]
    for sql in cases:
        assert "date(created_at" not in sql, sql
        assert "strftime('%s', created_at" not in sql, sql
