"""运行状态统计模块测试 —— 采集、环形缓冲、snapshot 聚合"""

import service.runtime_status_service as rsm
from service.runtime_status_service import (
    RuntimeStatusService,
    get_runtime_status,
    reset_runtime_status,
)


def test_snapshot_before_startup_is_stopped() -> None:
    service = RuntimeStatusService()
    snapshot = service.snapshot()
    assert snapshot["status"] == "stopped"
    assert snapshot["started_at"] is None
    assert snapshot["check_count"] == 0
    assert snapshot["last_tick"] is None


def test_record_tick_and_snapshot() -> None:
    service = RuntimeStatusService()
    service.record_startup(check_interval=10.0, monitor_symbols=["gds_AUTD"])
    service.record_tick(ok=True, latency_ms=120.5, price=906.8, events=1)
    service.record_tick(ok=False, latency_ms=80.0, detail="main_price_missing")

    snapshot = service.snapshot()
    assert snapshot["status"] == "running"
    assert snapshot["started_at"] is not None
    assert snapshot["uptime_seconds"] is not None
    assert snapshot["check_count"] == 2
    assert snapshot["alert_count"] == 1

    # recent_ticks 倒序：最新在前
    assert snapshot["last_tick"]["ok"] is False
    assert snapshot["last_tick"]["detail"] == "main_price_missing"
    assert snapshot["recent_ticks"][1]["ok"] is True
    assert snapshot["recent_ticks"][1]["price"] == 906.8

    assert snapshot["ticks_1h"] == 2
    assert snapshot["failed_1h"] == 1
    assert snapshot["avg_latency_ms_1h"] == 100.2  # (120.5+80.0)/2 保留 1 位小数
    assert snapshot["last_error"] is None


def test_record_error_keeps_latest() -> None:
    service = RuntimeStatusService()
    service.record_error("ValueError: a")
    service.record_error("RuntimeError: b")

    snapshot = service.snapshot()
    assert snapshot["last_error"] is not None
    assert "RuntimeError: b" in snapshot["last_error"]["message"]
    assert snapshot["check_count"] == 0, "错误不打断巡检计数"


def test_ring_buffer_caps_recent_ticks(monkeypatch) -> None:
    """环形缓冲上限：超过 MAX_RECENT_TICKS 后丢弃最旧记录"""
    monkeypatch.setattr(rsm, "MAX_RECENT_TICKS", 5)
    service = RuntimeStatusService()
    for _ in range(8):
        service.record_tick(ok=True, latency_ms=10.0)
    snapshot = service.snapshot()
    # snapshot 展示条数受 SNAPSHOT_TICKS 与缓冲上限共同约束
    assert len(snapshot["recent_ticks"]) == 5
    assert snapshot["check_count"] == 8, "计数是累计的，不随缓冲截断"


def test_singleton_and_reset() -> None:
    reset_runtime_status()
    first = get_runtime_status()
    assert get_runtime_status() is first
    reset_runtime_status()
    assert get_runtime_status() is not first
    reset_runtime_status()
