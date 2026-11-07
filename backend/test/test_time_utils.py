"""utils.time_utils 时间工具测试。"""
from datetime import datetime

from utils.time_utils import CHINA_TZ, from_timestamp, parse_date, today, today_end


def test_parse_date_basic():
    dt = parse_date("2026-01-15")
    assert dt == datetime(2026, 1, 15, 0, 0, 0, tzinfo=CHINA_TZ)


def test_parse_date_with_time():
    dt = parse_date("2026-01-15", hour=23, minute=59, second=59)
    assert dt.hour == 23
    assert dt.minute == 59
    assert dt.second == 59
    assert dt.tzinfo == CHINA_TZ


def test_from_timestamp_roundtrip():
    ts = 1736899200.0  # 2026-01-15 08:00:00 UTC+8 附近
    dt = from_timestamp(ts)
    assert dt.tzinfo == CHINA_TZ
    assert int(dt.timestamp()) == int(ts)


def test_today_boundaries():
    start = today()
    end = today_end()
    assert start.hour == 0 and start.minute == 0 and start.second == 0
    assert end.hour == 23 and end.minute == 59 and end.second == 59
    assert start.tzinfo == CHINA_TZ and end.tzinfo == CHINA_TZ
