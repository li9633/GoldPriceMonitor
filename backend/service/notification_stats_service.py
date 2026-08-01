from mapper.notification_stats_mapper import NotificationStatsMapper
from models.notification_stats import (
    ChannelStatsItem,
    DailyTrendItem,
    FailureReasonItem,
    NotifyLogItem,
    NotifyStatsOverview,
)
from utils.logger import get_logger

logger = get_logger("NotificationStatsService")

_ERROR_TYPE_LABELS = {
    "network_timeout": "网络超时",
    "auth_failed": "认证失败",
    "config_missing": "配置缺失",
    "api_error": "API 错误",
    "rate_limited": "频率限制",
    "unknown": "未分类",
}


class NotificationStatsService:
    def __init__(self) -> None:
        self.mapper = NotificationStatsMapper()
        self.mapper.init_tables()

    def log_send(
        self,
        alert_level: str,
        symbol: str,
        symbol_name: str,
        current_price: float | None,
        alert_summary: str,
        channel_type: str,
        channel_name: str,
        chain_id: str,
        chain_position: int,
        chain_total: int,
        success: bool,
        latency_ms: float | None,
        error_type: str,
        error_reason: str,
    ) -> None:
        self.mapper.insert_log(
            alert_level=alert_level,
            symbol=symbol,
            symbol_name=symbol_name,
            current_price=current_price,
            alert_summary=alert_summary,
            channel_type=channel_type,
            channel_name=channel_name,
            chain_id=chain_id,
            chain_position=chain_position,
            chain_total=chain_total,
            success=success,
            latency_ms=latency_ms,
            error_type=error_type,
            error_reason=error_reason,
        )

    def get_overview(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> NotifyStatsOverview:
        raw = self.mapper.get_overview(hours, start_date, end_date)
        return NotifyStatsOverview(**raw)

    def get_top_failures(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[FailureReasonItem]:
        raw = self.mapper.get_top_failures(hours, start_date, end_date)
        return [
            FailureReasonItem(
                error_type=r["error_type"],
                error_type_label=_ERROR_TYPE_LABELS.get(r["error_type"])
                or r["error_type"],
                fail_count=r["fail_count"],
                percentage=r["percentage"],
                examples=r["examples"],
            )
            for r in raw
        ]

    def get_channel_stats(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[ChannelStatsItem]:
        raw = self.mapper.get_channel_stats(hours, start_date, end_date)
        return [ChannelStatsItem(**r) for r in raw]

    def get_daily_trend(
        self,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[DailyTrendItem]:
        raw = self.mapper.get_daily_trend(hours, start_date, end_date)
        return [DailyTrendItem(**r) for r in raw]

    def get_logs(
        self,
        page: int,
        page_size: int,
        hours: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[list[NotifyLogItem], int]:
        rows, total = self.mapper.get_logs(page, page_size, hours, start_date, end_date)
        return [NotifyLogItem(**r) for r in rows], total

    def get_chain_detail(self, chain_id: str) -> list[NotifyLogItem]:
        rows = self.mapper.get_chain_detail(chain_id)
        return [NotifyLogItem(**r) for r in rows]
