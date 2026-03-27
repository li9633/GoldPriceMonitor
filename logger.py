import os
import logging
import gzip
import shutil
from datetime import datetime
from typing import Optional
from logging.handlers import RotatingFileHandler


class Logger:
    """
    自定义日志类，支持：
    - 多级别日志（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    - 文件轮转（大小限制 + 备份数量）
    - 自动压缩归档旧日志
    - 控制台 + 文件双输出
    """

    def __init__(
        self,
        name: str = "GoldPriceMonitor",
        log_dir: str = "logs",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        compress_backup: bool = True,
        console_output: bool = True
    ):
        self.name = name
        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.compress_backup = compress_backup
        self.console_output = console_output

        # 创建日志目录
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 初始化日志记录器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # 清除已有的处理器（避免重复）
        self.logger.handlers.clear()

        # 添加文件处理器
        self._add_file_handler()

        # 添加控制台处理器
        if console_output:
            self._add_console_handler()

    def _add_file_handler(self):
        """添加文件轮转处理器"""
        log_file = os.path.join(self.log_dir, f"{self.name}.log")

        # 使用 RotatingFileHandler 实现文件轮转
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # 设置日志格式
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        # 添加轮转监听器，用于压缩旧日志
        file_handler.rotator = self._compress_rotator
        file_handler.namer = self._log_namer

        self.logger.addHandler(file_handler)

    def _add_console_handler(self):
        """添加控制台处理器"""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)  # 控制台只显示 INFO 及以上

        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)

        self.logger.addHandler(console_handler)

    def _log_namer(self, name: str) -> str:
        """
        日志文件命名规则
        app.log -> app.log.1 -> app.log.2 -> ...
        """
        return name

    def _compress_rotator(self, source: str, dest: str):
        """
        日志轮转时压缩旧日志文件
        将 source 压缩为 dest.gz
        """
        if self.compress_backup:
            try:
                # 压缩源文件
                compressed_file = f"{dest}.gz"
                with open(source, 'rb') as f_in:
                    with gzip.open(compressed_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)

                # 删除原始轮转文件
                if os.path.exists(source):
                    os.remove(source)

                self.logger.info(f"日志已压缩归档：{compressed_file}")
            except Exception as e:
                self.logger.error(f"日志压缩失败：{e}")
                # 压缩失败则直接移动文件
                if os.path.exists(source):
                    shutil.move(source, dest)
        else:
            # 不压缩，直接移动
            if os.path.exists(source):
                shutil.move(source, dest)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str, exc_info: Optional[Exception] = None):
        if exc_info:
            self.logger.error(msg, exc_info=True)
        else:
            self.logger.error(msg)

    def critical(self, msg: str, exc_info: Optional[Exception] = None):
        if exc_info:
            self.logger.critical(msg, exc_info=True)
        else:
            self.logger.critical(msg)

    def get_log_files(self) -> list:
        """获取所有日志文件列表"""
        files = []
        if os.path.exists(self.log_dir):
            for f in os.listdir(self.log_dir):
                if f.startswith(self.name) and (f.endswith('.log') or f.endswith('.log.gz')):
                    files.append(os.path.join(self.log_dir, f))
        return sorted(files, reverse=True)

    def get_log_size(self) -> int:
        """获取当前日志文件大小（字节）"""
        log_file = os.path.join(self.log_dir, f"{self.name}.log")
        if os.path.exists(log_file):
            return os.path.getsize(log_file)
        return 0

    def cleanup_old_logs(self, keep_days: int = 30):
        """
        清理超过指定天数的旧日志
        Args:
            keep_days: 保留天数
        """
        cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)

        for log_file in self.get_log_files():
            try:
                file_mtime = os.path.getmtime(log_file)
                if file_mtime < cutoff_time:
                    os.remove(log_file)
                    self.info(f"已删除过期日志：{log_file}")
            except Exception as e:
                self.error(f"删除日志失败 {log_file}: {e}")


# 全局日志实例
global_logger: Optional[Logger] = None


def get_logger(name: str = "GoldPriceMonitor") -> Logger:
    """获取全局日志实例"""
    global global_logger
    if global_logger is None:
        global_logger = Logger(name=name)
    return global_logger
