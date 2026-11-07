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
#: 默认日志等级 —— DB 未配置 / 读取失败 / 非法值时的兜底。
#: 只影响「未显式设置过」的环境；设置页保存的等级存进 DB 后优先生效。
_DEFAULT_LOG_LEVEL = "WARNING"
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
        return cfg.get("log_level", _DEFAULT_LOG_LEVEL)
    except ImportError:
        return _DEFAULT_LOG_LEVEL


def _init() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(_get_log_level())

    # 抑制第三方库的 DEBUG 日志
    for lib in _third_party_libs:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # 文件处理器 — 所有日志写入同一个文件。
    # 级别保持 DEBUG：root 级别是唯一闸门（DB 配置可随时切回 DEBUG 而无需
    # 重建 handler）；handler 只负责落盘不重复过滤。
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

    # 从 DB 读取日志等级（未配置时回落到 _DEFAULT_LOG_LEVEL）
    log_level = _get_log_level_from_db()
    root.setLevel(getattr(logging, log_level, logging.WARNING))


def _get_log_level() -> int:
    """初始化阶段的日志等级：先尝试 DB 配置，失败回落默认"""
    try:
        return getattr(logging, _get_log_level_from_db(), logging.WARNING)
    except Exception:  # noqa: BLE001 — 初始化期间任何异常都不应阻断启动
        return logging.WARNING


def apply_log_level(level: str) -> None:
    root = logging.getLogger()
    py_level = getattr(logging, level.upper(), logging.WARNING)
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
