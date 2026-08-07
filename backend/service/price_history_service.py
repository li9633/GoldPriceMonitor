from mapper.ai_stats_mapper import AiStatsMapper
from mapper.notification_stats_mapper import NotificationStatsMapper
from mapper.price_mapper import PriceMapper
from models.exchange_rate import ExchangeRateDashboardItem
from models.price import (
    AiDashboardStats,
    DashboardResponse,
    NotificationDashboardStats,
    PriceChartPoint,
    PriceDashboardStats,
    PriceRecordResponse,
    PriceSnapshotResponse,
    PriceStatistics,
    PriceTrend,
    SymbolDashboardItem,
)
from service.exchange_rate_service import ExchangeRateService
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

logger = get_logger("PriceHistoryService")


class PriceHistoryService:
    """金价历史查询服务 — 纯读操作"""

    def __init__(self) -> None:
        self.mapper = PriceMapper()
        self.ai_stats_mapper = AiStatsMapper()
        self.notify_stats_mapper = NotificationStatsMapper()
        self.exchange_rate_service = ExchangeRateService()

    # ==================== 记录数 ====================

    def get_record_count(self, symbol: str) -> int:
        return self.mapper.get_record_count(symbol)

    # ==================== 统计信息 ====================

    def get_statistics(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> PriceStatistics | None:
        raw = self.mapper.get_price_statistics(symbol, hours, start_date, end_date)
        if not raw:
            return None
        return PriceStatistics(**raw)

    # ==================== 趋势 ====================

    def get_trend(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> PriceTrend:
        raw = self.mapper.get_price_trend(symbol, hours, start_date, end_date)
        return PriceTrend(**raw)

    # ==================== 快照 ====================

    def get_snapshot(
        self, symbol: str, current_price: float | None = None
    ) -> PriceSnapshotResponse | None:
        snapshot = self.mapper.get_check_snapshot(symbol)
        if not snapshot:
            return None

        if current_price is None:
            recent = snapshot.prices_last_n(1)
            current_price = recent[0] if recent else 0.0

        stats_24h = snapshot.statistics(24)
        trend_6h = snapshot.trend(6)
        trend_24h = snapshot.trend(24)

        return PriceSnapshotResponse(
            symbol=symbol,
            current_price=current_price,
            statistics_24h=PriceStatistics(**stats_24h) if stats_24h else None,
            trend_6h=PriceTrend(**trend_6h),
            trend_24h=PriceTrend(**trend_24h),
            ma_5=snapshot.ma(5),
            ma_10=snapshot.ma(10),
            ma_20=snapshot.ma(20),
            min_3m=snapshot.min_3m,
            min_6m=snapshot.min_6m,
            recent_prices=snapshot.prices_last_n(5),
        )

    # ==================== 仪表盘 ====================

    def get_dashboard(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        hours: int | None = None,
    ) -> DashboardResponse:
        raw = self.mapper.get_dashboard_data(start_date, end_date, hours)
        settings = SystemSettingsService()
        symbol_name_map = settings.get_symbol_name_map()
        monitor_config = settings.get_monitor_config()

        symbols = []
        for item in raw["symbols"]:
            symbols.append(
                SymbolDashboardItem(
                    symbol=item["symbol"],
                    name=symbol_name_map.get(item["symbol"], str(item["symbol"])),
                    count=item["count"],
                    latest_price=item["latest_price"],
                    latest_time=item["latest_time"],
                    today_high=item["today_high"],
                    today_low=item["today_low"],
                    data_freshness_seconds=item["data_freshness_seconds"],
                )
            )

        ai_raw = self.ai_stats_mapper.get_simple_stats(start_date, end_date)
        notify_raw = self.notify_stats_mapper.get_simple_stats(start_date, end_date)
        exchange_rate_raw = self.exchange_rate_service.mapper.get_dashboard_data(
            start_date, end_date, hours
        )

        return DashboardResponse(
            start_date=start_date or "",
            end_date=end_date or "",
            price=PriceDashboardStats(
                total_records=raw["total_records"],
                new_records=raw["new_records"],
                symbols=symbols,
            ),
            ai=AiDashboardStats(**ai_raw),
            notification=NotificationDashboardStats(**notify_raw),
            active_symbols_count=len(monitor_config.get("monitor_symbols", [])),
            monitored_symbols=monitor_config.get("monitor_symbols", []),
            main_symbol=monitor_config.get("main_symbol", ""),
            exchange_rate=ExchangeRateDashboardItem(**exchange_rate_raw),
        )

    # ==================== 图表数据 ====================

    def get_chart_data(
        self,
        symbol: str,
        hours: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[PriceChartPoint]:
        rows = self.mapper.get_chart_series(symbol, hours, start_date, end_date)
        return [PriceChartPoint(timestamp=ts, price=p) for ts, p in rows]

    # ==================== 最近记录 ====================

    def get_recent_records(
        self, symbol: str, limit: int = 20
    ) -> list[PriceRecordResponse]:
        rows = self.mapper.get_price_series(symbol, 24)
        rows = rows[-limit:] if len(rows) > limit else rows
        return [
            PriceRecordResponse(
                id=0,
                symbol=symbol,
                price=p,
                timestamp=ts,
            )
            for ts, p in rows
        ]
