import gzip
import logging
import os
import shutil
from logging.handlers import RotatingFileHandler

from utils.time_utils import now

_LOG_DIR = "logs"
_LOG_NAME = "GoldPriceMonitor"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_initialized = False

# 运行时引用，避免循环导入
_console_handler: logging.StreamHandler | None = None
_third_party_libs = (
    "urllib3",
    "requests",
    "charset_normalizer",
    "certifi",
    "fastapi",
    "uvicorn",
    "asyncio",
)


def _get_log_level_from_db() -> str:
    try:
        from service.system_settings_service import SystemSettingsService

        cfg = SystemSettingsService().get_log_config()
        return cfg.get("log_level", "DEBUG")
    except ImportError:
        return "DEBUG"


def _init() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 抑制第三方库的 DEBUG 日志
    for lib in _third_party_libs:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # 文件处理器 — 所有日志写入同一个文件
    log_file = os.path.join(_LOG_DIR, f"{_LOG_NAME}.log")
    fh = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-14s | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    fh.rotator = _compress_rotator
    fh.namer = _log_namer
    root.addHandler(fh)

    # 控制台处理器
    global _console_handler
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(_console_handler)

    # 从 DB 读取日志等级，默认 DEBUG
    log_level = _get_log_level_from_db()
    root.setLevel(getattr(logging, log_level, logging.DEBUG))


def apply_log_level(level: str) -> None:
    root = logging.getLogger()
    py_level = getattr(logging, level.upper(), logging.DEBUG)
    root.setLevel(py_level)
    if _console_handler:
        _console_handler.setLevel(py_level)


def _log_namer(name: str) -> str:
    return name


def _compress_rotator(source: str, dest: str) -> None:
    try:
        compressed = f"{dest}.gz"
        with open(source, "rb") as f_in, gzip.open(compressed, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        if os.path.exists(source):
            os.remove(source)
    except OSError:
        if os.path.exists(source):
            shutil.move(source, dest)


def get_logger(name: str = "GoldPriceMonitor") -> logging.Logger:
    """获取模块级日志记录器，所有日志统一写入 GoldPriceMonitor.log"""
    _init()
    return logging.getLogger(name)


def get_log_size() -> int:
    log_file = os.path.join(_LOG_DIR, f"{_LOG_NAME}.log")
    if os.path.exists(log_file):
        return os.path.getsize(log_file)
    return 0


def cleanup_old_logs(keep_days: int = 30) -> None:
    cutoff = now().timestamp() - keep_days * 86400
    if not os.path.exists(_LOG_DIR):
        return
    for f in os.listdir(_LOG_DIR):
        if f.startswith(_LOG_NAME) and f.endswith((".log", ".log.gz")):
            fp = os.path.join(_LOG_DIR, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except OSError:
                pass
