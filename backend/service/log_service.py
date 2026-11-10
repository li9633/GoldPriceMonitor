import os
import threading

from utils.logger import _LOG_DIR, _LOG_NAME, get_logger

logger = get_logger("LogService")

_CHUNK_SIZE = 8192

#: 「总行数」缓存：按 (路径, 大小, mtime_ns, 过滤条件) 做键。
#:
#: 前端日志页每 10 秒轮询一次，而 `total_lines` 必须扫全文件才能得到 ——
#: 实测 10 MB（轮转上限）日志无过滤 10.9ms、带级别过滤 **70.2ms**。
#: 日志文件只在写日志时变化，所以绝大多数轮询可以直接命中缓存。
#: 只保留最近几条，避免过滤条件组合把内存撑开。
_COUNT_CACHE_MAX = 8
_count_cache: dict[tuple, int] = {}
_cache_lock = threading.Lock()


class LogService:
    """系统日志读取服务"""

    def get_content(
        self,
        lines: int,
        offset: int = 0,
        level: str | None = None,
        search: str | None = None,
    ) -> dict:
        log_path = os.path.join(_LOG_DIR, f"{_LOG_NAME}.log")
        content_lines, total = self._read_lines_reverse(
            log_path,
            max_lines=lines,
            offset=offset,
            level_filter=level,
            search=search,
        )
        file_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        return {
            "lines": content_lines,
            "total_lines": total,
            "file_size": file_size,
            "file_name": f"{_LOG_NAME}.log",
        }

    @staticmethod
    def _read_lines_reverse(
        file_path: str,
        max_lines: int,
        offset: int = 0,
        level_filter: str | None = None,
        search: str | None = None,
    ) -> tuple[list[str], int]:
        if not os.path.exists(file_path):
            return [], 0

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return [], 0

        collected: list[str] = []
        remainder = b""
        pos = file_size
        skip_count = offset

        with open(file_path, "rb") as f:
            while pos > 0 and len(collected) < max_lines + skip_count:
                read_size = min(_CHUNK_SIZE, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                if remainder:
                    chunk += remainder
                raw_lines = chunk.split(b"\n")
                if pos == 0:
                    remainder = b""
                else:
                    remainder = raw_lines[0]
                    raw_lines = raw_lines[1:]
                for raw_line in reversed(raw_lines):
                    if not raw_line:
                        continue
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                    except UnicodeDecodeError:
                        continue
                    if level_filter and not LogService._match_level(line, level_filter):
                        continue
                    if search and search not in line:
                        continue
                    if skip_count > 0:
                        skip_count -= 1
                        continue
                    collected.append(line)
                    if len(collected) >= max_lines:
                        break

        total = LogService._count_matching_lines(file_path, level_filter, search)
        collected.reverse()
        return collected, total

    @staticmethod
    def _match_level(line: str, level: str) -> bool:
        markers = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level_upper = level.upper()
        if level_upper not in markers:
            return True
        for marker in markers:
            if marker in line:
                return marker == level_upper
        return False

    @staticmethod
    def _count_matching_lines(
        file_path: str,
        level_filter: str | None,
        search: str | None,
    ) -> int:
        if not os.path.exists(file_path):
            return 0

        stat = os.stat(file_path)
        key = (file_path, stat.st_size, stat.st_mtime_ns, level_filter, search)
        with _cache_lock:
            cached = _count_cache.get(key)
        if cached is not None:
            return cached

        if not level_filter and not search:
            with open(file_path, "rb") as f:
                count = sum(1 for _ in f)
        else:
            count = 0
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line:
                        continue
                    if level_filter and not LogService._match_level(line, level_filter):
                        continue
                    if search and search not in line:
                        continue
                    count += 1

        with _cache_lock:
            if len(_count_cache) >= _COUNT_CACHE_MAX:
                _count_cache.clear()
            _count_cache[key] = count
        return count
