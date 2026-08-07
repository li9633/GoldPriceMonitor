from mapper.exchange_rate_mapper import ExchangeRateMapper
from models.exchange_rate import (
    ExchangeRateChartPoint,
    ExchangeRateDashboardItem,
    ExchangeRateStatistics,
    ExchangeRateTrend,
)
from utils.logger import get_logger

logger = get_logger("ExchangeRateService")


class ExchangeRateService:
    """汇率历史查询服务 — 纯读操作"""

    def __init__(self) -> None:
        self.mapper = ExchangeRateMapper()

    def get_record_count(self) -> int:
        return self.mapper.get_record_count()

    def get_statistics(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ExchangeRateStatistics | None:
        raw = self.mapper.get_statistics(hours, start_date, end_date)
        if not raw:
            return None
        return ExchangeRateStatistics(**raw)

    def get_trend(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ExchangeRateTrend:
        raw = self.mapper.get_trend(hours, start_date, end_date)
        return ExchangeRateTrend(**raw)

    def get_chart_data(
        self,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[ExchangeRateChartPoint]:
        rows = self.mapper.get_chart_series(hours, start_date, end_date)
        return [ExchangeRateChartPoint(timestamp=ts, rate=rate) for ts, rate in rows]

    def get_recent_records(
        self, hours: float = 24, limit: int = 20
    ) -> list[ExchangeRateChartPoint]:
        rows = self.mapper.get_recent_records(hours, limit)
        return [ExchangeRateChartPoint(timestamp=ts, rate=rate) for ts, rate in rows]

    def get_dashboard(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> ExchangeRateDashboardItem:
        raw = self.mapper.get_dashboard_data(start_date, end_date, hours)
        return ExchangeRateDashboardItem(**raw)
