import argparse
import signal
import sqlite3
import sys
import threading

import uvicorn

from app import app
from mapper.price_mapper import PriceMapper
from service.monitor_service import MonitorService
from utils.logger import get_logger

logger = get_logger("Main")

DEFAULT_PORT = 8000


def _shutdown(signum: int, _frame) -> None:
    """SIGTERM/SIGINT 信号处理：强制 checkpoint 后安全退出"""
    sig_name = signal.Signals(signum).name
    logger.info(f"收到 {sig_name} 信号，正在安全关闭...")
    try:
        PriceMapper().checkpoint()
    except (OSError, sqlite3.Error) as e:
        logger.error(f"关闭时 checkpoint 失败：{e}")
    sys.exit(0)


def _start_monitor() -> None:
    """后台线程：启动价格监控"""
    try:
        MonitorService().run()
    except Exception as e:
        logger.error(f"监控服务异常退出：{e}", exc_info=e)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    parser = argparse.ArgumentParser(description="黄金价格智能监控系统")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"服务端口（默认: {DEFAULT_PORT}）",
    )
    args = parser.parse_args()

    monitor_thread = threading.Thread(
        target=_start_monitor, daemon=True, name="MonitorThread"
    )
    monitor_thread.start()

    logger.info("服务启动完成 http://0.0.0.0:%d", args.port)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
