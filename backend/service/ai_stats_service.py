from datetime import datetime

from config import CHINA_TZ
from mapper.ai_stats_mapper import AiStatsMapper
from mapper.model_pricing_mapper import ModelPricingMapper
from models.ai_stats import (
    AiCallLogItem,
    AiStatsOverview,
    DailyTrendItem,
    FailureReasonItem,
    HourlyItem,
    ModelRankingItem,
    ProviderFailureItem,
    ProviderRankingItem,
    TokenByModel,
    TokenDailyTrend,
    TokenOverview,
    TopModelItem,
    TopProviderItem,
)
from utils.logger import get_logger

logger = get_logger("AiStatsService")


class AiStatsService:
    def __init__(self) -> None:
        self.mapper = AiStatsMapper()
        self.mapper.init_tables()
        self.pricing_mapper = ModelPricingMapper()
        self.pricing_mapper.init_table()

    def log_call(
        self,
        provider_name: str,
        model_name: str,
        success: bool,
        latency_ms: int | None,
        error_reason: str | None,
        from_cache: bool,
        triggered_alerts: str | None,
    ) -> None:
        self.mapper.insert_log(
            provider_name=provider_name,
            model_name=model_name,
            call_time=datetime.now(CHINA_TZ),
            success=success,
            latency_ms=latency_ms,
            error_reason=error_reason,
            from_cache=from_cache,
            triggered_alerts=triggered_alerts,
        )

    def get_overview(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> AiStatsOverview:
        raw = self.mapper.get_overview_raw(start_date, end_date)
        today_total = raw["today_total"]
        today_success = raw["today_success"]
        today_failure = today_total - today_success
        success_rate = (
            round(100.0 * today_success / today_total, 1) if today_total else 0.0
        )
        failure_rate = round(100 - success_rate, 1)
        timeout_rate = (
            round(100.0 * raw["timeout_count"] / today_total, 1) if today_total else 0.0
        )
        cache_hit_rate = (
            round(100.0 * raw["today_cache"] / today_total, 1) if today_total else 0.0
        )

        latencies = raw["latencies"]
        p50 = self._percentile(latencies, 50)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)

        consecutive = self.mapper.get_consecutive_failures()

        return AiStatsOverview(
            today_total=today_total,
            today_success=today_success,
            today_failure=today_failure,
            success_rate=success_rate,
            failure_rate=failure_rate,
            consecutive_failures=consecutive,
            last_success_time=raw["last_success_time"],
            avg_latency_ms=round(raw["avg_latency"], 1),
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            p99_latency_ms=p99,
            timeout_rate=timeout_rate,
            total_all=raw["total_all"],
            cache_hit_count=raw["today_cache"],
            cache_hit_rate=cache_hit_rate,
            top_model=TopModelItem(**raw["top_model"]) if raw["top_model"] else None,
            top_provider=TopProviderItem(**raw["top_provider"])
            if raw["top_provider"]
            else None,
            top_failures=[FailureReasonItem(**f) for f in raw["top_failures"]],
            hourly_distribution=[HourlyItem(**h) for h in raw["hourly"]],
            model_ranking=[ModelRankingItem(**m) for m in raw["model_ranking"]],
            provider_ranking=[
                ProviderRankingItem(**p) for p in raw["provider_ranking"]
            ],
            provider_failures=[
                ProviderFailureItem(**p) for p in raw["provider_failures"]
            ],
        )

    def get_daily_trend(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[DailyTrendItem]:
        rows = self.mapper.get_daily_trend(start_date, end_date)
        return [
            DailyTrendItem(
                date=r["date"],
                hour=r["hour"],
                total=r["total"],
                success_count=r["success_count"],
                success_rate=round(100.0 * r["success_count"] / r["total"], 1)
                if r["total"]
                else 0.0,
                avg_latency=round(r["avg_latency"], 1),
            )
            for r in rows
        ]

    def get_recent_logs(
        self,
        page: int,
        page_size: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[list[AiCallLogItem], int]:
        rows, total = self.mapper.get_recent_logs(page, page_size, start_date, end_date)
        return [AiCallLogItem(**r) for r in rows], total

    @staticmethod
    def _percentile(sorted_data: list[int | float], p: float) -> float:
        if not sorted_data:
            return 0.0
        n = len(sorted_data)
        k = (p / 100) * (n - 1)
        f = int(k)
        c = k - f
        if f + 1 < n:
            return round(sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f]), 1)
        return round(float(sorted_data[f]), 1)

    def _compute_cost(
        self,
        provider_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        pricing = self.pricing_mapper.get_by_provider_model(provider_name, model_name)
        if not pricing:
            return 0.0
        input_cost = (prompt_tokens / 1_000_000) * pricing["input_price"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output_price"]
        return round(input_cost + output_cost, 6)

    def get_token_overview(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> TokenOverview:
        raw = self.mapper.get_token_overview(start_date, end_date)
        cost = self._compute_cost(
            "", "", raw["prompt_tokens"], raw["completion_tokens"]
        )
        return TokenOverview(estimated_cost=cost, **raw)

    def get_token_by_model(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[TokenByModel]:
        rows = self.mapper.get_token_by_model(start_date, end_date)
        return [
            TokenByModel(
                estimated_cost=self._compute_cost(
                    r["provider_name"],
                    r["model_name"],
                    r["prompt_tokens"],
                    r["completion_tokens"],
                ),
                **r,
            )
            for r in rows
        ]

    def get_token_daily_trend(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[TokenDailyTrend]:
        rows = self.mapper.get_token_daily_trend(start_date, end_date)
        return [
            TokenDailyTrend(
                date=r["date"],
                hour=r["hour"],
                prompt_tokens=r["prompt_tokens"],
                completion_tokens=r["completion_tokens"],
                total_tokens=r["total_tokens"],
                calls=r["calls"],
                estimated_cost=self._compute_cost(
                    "", "", r["prompt_tokens"], r["completion_tokens"]
                ),
            )
            for r in rows
        ]
