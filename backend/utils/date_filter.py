"""统一日期筛选工具 — 所有统计接口共用

安全约束：`start_date` / `end_date` 会被拼进 SQL 字符串，因此**必须严格校验**。
历史上这里直接 `f"... >= '{start_date}'"`，导致
`start_date=2020-01-01' OR '1'='1` 可以短路过滤条件、甚至拼出 UNION 子句。
现在改为：格式不符直接抛 `InvalidDateError`（API 层转 400），
校验通过后字符串里只可能出现数字和短横线，拼接才是安全的。
"""

from utils.time_utils import InvalidDateError, safe_date_str

__all__ = ["InvalidDateError", "build_date_filter"]


def _safe_date(value: str, field: str) -> str:
    """校验并返回可以安全拼进 SQL 的日期字符串"""
    return safe_date_str(value, field)


def build_date_filter(
    hours: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    time_column: str = "created_at",
    time_format: str = "datetime",
) -> str:
    """构建统一的日期筛选 SQL WHERE 子句

    优先级：hours > start_date/end_date > 默认今天

    Args:
        hours: 最近N小时（覆盖日期参数）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        time_column: 时间列名
        time_format: 'datetime'（文本时间戳）或 'unixepoch'（Unix 时间戳）

    Returns:
        SQL WHERE 子句字符串

    Raises:
        InvalidDateError: 日期参数不是合法的 YYYY-MM-DD
        ValueError: time_column 不是合法标识符（防止列名注入）
    """
    # 列名来自代码常量，但仍然校验一次：别让参数里能塞进 SQL 片段
    if not time_column.isidentifier():
        raise ValueError(f"非法的列名：{time_column!r}")

    # 空串（`?start_date=`）视同「没传」，否则前端清空日期框会直接 400
    start_date = start_date or None
    end_date = end_date or None
    if start_date is not None:
        start_date = _safe_date(start_date, "start_date")
    if end_date is not None:
        end_date = _safe_date(end_date, "end_date")

    if hours is not None and hours > 0:
        hours = int(hours)
        if time_format == "unixepoch":
            return (
                f"{time_column} >= strftime('%s', 'now', 'localtime', '-{hours} hours')"
            )
        return f"{time_column} >= datetime('now', 'localtime', '-{hours} hours')"

    if time_format == "unixepoch":
        date_expr = f"date({time_column}, 'unixepoch', 'localtime')"
        if start_date and end_date:
            return f"{date_expr} BETWEEN '{start_date}' AND '{end_date}'"
        if start_date:
            return f"{date_expr} >= '{start_date}'"
        if end_date:
            return f"{date_expr} <= '{end_date}'"
        return f"{date_expr} = date('now', 'localtime')"

    # 文本时间列（'YYYY-MM-DD HH:MM:SS'）按字符串比较与按日期比较等价，
    # 但**不要把列包进 date()** —— 一旦 `date(call_time) = ...`，列上就不能用
    # 索引了，200k 行的统计查询会退化成全表扫描（实测单次 32ms × 十几条）。
    # 这里统一写成半开区间，列保持裸露，索引（idx_ai_logs_call_time 等）可用。
    if start_date and end_date:
        return (
            f"{time_column} >= '{start_date}' "
            f"AND {time_column} < date('{end_date}', '+1 day')"
        )
    if start_date:
        return f"{time_column} >= '{start_date}'"
    if end_date:
        return f"{time_column} < date('{end_date}', '+1 day')"
    return (
        f"{time_column} >= date('now', 'localtime') "
        f"AND {time_column} < date('now', 'localtime', '+1 day')"
    )
