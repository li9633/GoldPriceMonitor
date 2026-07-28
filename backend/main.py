import threading

import uvicorn

from app import app
from service.monitor_service import MonitorService
from utils.logger import get_logger

logger = get_logger("Main")


def _start_monitor() -> None:
    """后台线程：启动价格监控"""
    try:
        MonitorService().run()
    except Exception as e:
        logger.error(f"监控服务异常退出：{e}", exc_info=e)


if __name__ == "__main__":
    monitor_thread = threading.Thread(
        target=_start_monitor, daemon=True, name="MonitorThread"
    )
    monitor_thread.start()
    logger.info("价格监控服务已在后台启动")

    logger.info("API 服务已启动，监听端口 http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
