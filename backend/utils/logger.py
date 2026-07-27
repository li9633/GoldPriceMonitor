import gzip
import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler

from config import CHINA_TZ

_LOG_DIR = "logs"
_LOG_NAME = "GoldPriceMonitor"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 抑制第三方库的 DEBUG 日志
    for lib in ("urllib3", "requests", "charset_normalizer", "certifi"):
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
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(ch)


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
    cutoff = datetime.now(CHINA_TZ).timestamp() - keep_days * 86400
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
