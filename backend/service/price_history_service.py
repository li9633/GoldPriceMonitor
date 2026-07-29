from mapper.price_mapper import PriceMapper
from models.price import (
    DashboardResponse,
    PriceChartPoint,
    PriceRecordResponse,
    PriceSnapshotResponse,
    PriceStatistics,
    PriceTrend,
    SymbolDashboardItem,
)
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

logger = get_logger("PriceHistoryService")


class PriceHistoryService:
    """金价历史查询服务 — 纯读操作"""

    def __init__(self) -> None:
        self.mapper = PriceMapper()

    # ==================== 记录数 ====================

    def get_record_count(self, symbol: str) -> int:
        return self.mapper.get_record_count(symbol)

    # ==================== 统计信息 ====================

    def get_statistics(self, symbol: str, hours: float) -> PriceStatistics | None:
        raw = self.mapper.get_price_statistics(symbol, hours)
        if not raw:
            return None
        return PriceStatistics(**raw)

    # ==================== 趋势 ====================

    def get_trend(self, symbol: str, hours: float) -> PriceTrend:
        raw = self.mapper.get_price_trend(symbol, hours)
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

    def get_dashboard(self) -> DashboardResponse:
        raw = self.mapper.get_dashboard_data()
        symbol_name_map = SystemSettingsService().get_symbol_name_map()
        symbols = []
        for item in raw["symbols"]:
            symbols.append(
                SymbolDashboardItem(
                    symbol=item["symbol"],
                    name=symbol_name_map.get(item["symbol"], str(item["symbol"])),
                    count=item["count"],
                    latest_price=item["latest_price"],
                    latest_time=item["latest_time"],
                )
            )
        return DashboardResponse(total_records=raw["total_records"], symbols=symbols)

    # ==================== 图表数据 ====================

    def get_chart_data(self, symbol: str, hours: float) -> list[PriceChartPoint]:
        rows = self.mapper.get_chart_series(symbol, hours)
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
