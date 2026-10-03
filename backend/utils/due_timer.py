"""到点判断 —— 按「上次运行时间 + 间隔」判断某件事是否该执行。

- 新增一个定时任务只需声明一个 timer
- 间隔可热更新（配置改了不用重启）
- 首次是否到点、禁用、剩余时间都有单测覆盖
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DueTimer:
    """按固定间隔判断某件事是否到点。

    `interval_seconds <= 0` 视为**不启用**，`is_due()` 恒为 `False`。
    """

    name: str = ""
    interval_seconds: float = 0.0
    _last: datetime | None = field(default=None, repr=False)

    @property
    def enabled(self) -> bool:
        return self.interval_seconds > 0

    @property
    def last_run(self) -> datetime | None:
        return self._last

    def is_due(self, at: datetime, *, never_run_is_due: bool = True) -> bool:
        """是否到点。

        `never_run_is_due=True`（默认）表示「从没跑过」也算到点 —— 这样进程启动后
        第一次巡检就会补齐，不必等一个完整间隔。
        """
        if not self.enabled:
            return False
        if self._last is None:
            return never_run_is_due
        return (at - self._last).total_seconds() >= self.interval_seconds

    def mark(self, at: datetime) -> None:
        self._last = at

    def seconds_until_due(self, at: datetime) -> float:
        if not self.enabled or self._last is None:
            return 0.0
        remaining = self.interval_seconds - (at - self._last).total_seconds()
        return max(remaining, 0.0)

    def reset(self) -> None:
        self._last = None

    def set_interval(self, seconds: float) -> None:
        """热更新间隔。

        刻意**不**重置 `_last` —— 否则每次改配置都会立刻触发一次，
        在巡检类任务上会造成「改一次配置就多发一条」的副作用。
        """
        self.interval_seconds = seconds
