"""运行状态统计 —— 程序自身运行指标的持续采集与查询。

设计动机：此前运行指标（巡检次数、投递次数）只按每 100 轮打印进日志，
人要看状态得翻日志文件。本模块把「程序跑得怎么样」变成可查询的一等数据：

- `record_startup()`：进程启动时登记（running 的依据）；
- `record_tick()`：每轮巡检结束（或提前退出）时记录一次 —— 时间、耗时、
  结果、主品种价格、本轮投递事件数，环形缓冲保留最近 N 条；
- `record_error()`：主循环捕获的异常；
- `snapshot()`：聚合成一个可直接给 API 返回的字典。

单线程写入（监控线程），多线程读（FastAPI 请求线程）；
deque 的 append 是原子的，读侧最多拿到瞬时不一致的视图，可接受。
"""

import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime

from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("RuntimeStatus")

#: 环形缓冲保留的最近巡检记录数（10s 间隔约对应 33 分钟）
MAX_RECENT_TICKS = 200
#: snapshot 里返回的最近记录条数（前端表格一屏量级）
SNAPSHOT_TICKS = 50


@dataclass
class TickRecord:
    """一轮巡检的记录"""

    at: str  # ISO 时间（北京时间）
    latency_ms: float
    ok: bool
    #: 失败/异常原因（ok=False 时有值），如 main_price_missing / exception
    detail: str = ""
    #: 主品种价格（缺失时为 None）
    price: float | None = None
    #: 本轮成功投递的事件数（建议/复盘/通知）
    events: int = 0


class RuntimeStatusService:
    """程序运行状态采集（进程内单例）"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at: datetime | None = None
        self._check_count = 0
        self._alert_count = 0
        self._ticks: deque[TickRecord] = deque(maxlen=MAX_RECENT_TICKS)
        self._last_error: dict | None = None

    # ==================== 采集（监控线程调用） ====================

    def record_startup(self, *, check_interval: float, monitor_symbols: list[str]) -> None:
        """进程启动时登记。重复调用（热重启）以最后一次为准。"""
        with self._lock:
            self._started_at = now()
        logger.info(
            f"运行状态采集已启动 check_interval={check_interval} "
            f"symbols={','.join(monitor_symbols)}"
        )

    def record_tick(
        self,
        *,
        ok: bool,
        latency_ms: float,
        price: float | None = None,
        events: int = 0,
        detail: str = "",
    ) -> None:
        """记录一轮巡检。ok=False 时 detail 说明原因。"""
        record = TickRecord(
            at=now().isoformat(timespec="seconds"),
            latency_ms=round(latency_ms, 1),
            ok=ok,
            detail=detail,
            price=price,
            events=events,
        )
        with self._lock:
            self._check_count += 1
            self._alert_count += events
            self._ticks.append(record)

    def record_error(self, message: str) -> None:
        """主循环捕获的异常（巡检中断，不产出 TickRecord）"""
        with self._lock:
            self._last_error = {
                "at": now().isoformat(timespec="seconds"),
                "message": message[:500],
            }

    # ==================== 查询（API 线程调用） ====================

    def snapshot(self) -> dict:
        with self._lock:
            started_at = self._started_at
            check_count = self._check_count
            alert_count = self._alert_count
            ticks = list(self._ticks)
            last_error = dict(self._last_error) if self._last_error else None

        recent = [asdict(t) for t in reversed(ticks[-SNAPSHOT_TICKS:])]
        last_tick = recent[0] if recent else None

        # 最近 1 小时窗口的巡检统计
        cutoff = (now().timestamp() - 3600) * 1000
        window = [
            t
            for t in ticks
            if _parse_iso_ms(t.at) is not None and _parse_iso_ms(t.at) >= cutoff
        ]
        latencies = [t.latency_ms for t in window]
        failed = [t for t in window if not t.ok]

        return {
            "status": "running" if started_at is not None else "stopped",
            "started_at": started_at.isoformat(timespec="seconds") if started_at else None,
            "uptime_seconds": (
                round((now() - started_at).total_seconds(), 1) if started_at else None
            ),
            "check_count": check_count,
            "alert_count": alert_count,
            "last_tick": last_tick,
            "ticks_1h": len(window),
            "failed_1h": len(failed),
            "avg_latency_ms_1h": (
                round(sum(latencies) / len(latencies), 1) if latencies else None
            ),
            "last_error": last_error,
            "recent_ticks": recent,
        }


def _parse_iso_ms(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp() * 1000
    except ValueError:
        return None


_instance: RuntimeStatusService | None = None
_instance_lock = threading.Lock()


def get_runtime_status() -> RuntimeStatusService:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = RuntimeStatusService()
        return _instance


def reset_runtime_status() -> None:
    """测试用：清空单例"""
    global _instance
    with _instance_lock:
        _instance = None
