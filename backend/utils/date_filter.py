"""统一日期筛选工具 — 所有统计接口共用"""


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
    """
    if hours is not None and hours > 0:
        if time_format == "unixepoch":
            return (
                f"{time_column} >= strftime('%s', 'now', 'localtime', '-{hours} hours')"
            )
        return f"{time_column} >= datetime('now', 'localtime', '-{hours} hours')"

    if time_format == "unixepoch":
        date_expr = f"date({time_column}, 'unixepoch', 'localtime')"
    else:
        date_expr = f"date({time_column})"

    if start_date and end_date:
        return f"{date_expr} BETWEEN '{start_date}' AND '{end_date}'"
    if start_date:
        return f"{date_expr} >= '{start_date}'"
    if end_date:
        return f"{date_expr} <= '{end_date}'"
    return f"{date_expr} = date('now', 'localtime')"
