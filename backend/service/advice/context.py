"""建议上下文：把「行情 + 持仓 + 计划 + 偏好」整理成一次建议所需的全部输入。

同时把 `PriceSnapshot` 序列化成可冻结的 `MarketIndicators`，
用于写进 `advice_records.evidence`。
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from mapper.price_mapper import PriceSnapshot
from models.advice import AdvicePrefs
from models.portfolio import PlanProgress, PositionSummary
from service.advice.entry_strategy import EntryStrategyResult
from service.advice.risk import RiskProfile, position_ratio_limit, resolve_risk
from utils.time_utils import now


@dataclass
class MarketIndicators:
    """从 `PriceSnapshot` 一次性提取的指标 —— 信号与证据共用同一组数字"""

    current_price: float
    london_cny: float | None = None
    london_usd: float | None = None
    avg_24h: float | None = None
    max_24h: float | None = None
    min_24h: float | None = None
    std_24h: float | None = None
    count_24h: int = 0
    volatility_pct: float | None = None
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    trend_6h_slope: float | None = None
    trend_6h_direction: str | None = None
    trend_24h_slope: float | None = None
    trend_24h_direction: str | None = None
    min_3m: float | None = None
    min_6m: float | None = None
    pct_from_3m_low: float | None = None
    pct_from_6m_low: float | None = None
    pct_from_24h_low: float | None = None
    pct_from_24h_high: float | None = None
    range_position_24h: float | None = None
    recent_prices: list[float] = field(default_factory=list)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: PriceSnapshot | None,
        current_price: float,
        london_cny: float | None = None,
        london_usd: float | None = None,
    ) -> "MarketIndicators":
        indicators = cls(
            current_price=current_price,
            london_cny=london_cny,
            london_usd=london_usd,
        )
        if snapshot is None:
            return indicators

        stats = snapshot.statistics(24) or {}
        if stats:
            indicators.avg_24h = stats.get("avg")
            indicators.max_24h = stats.get("max")
            indicators.min_24h = stats.get("min")
            indicators.std_24h = stats.get("std")
            indicators.count_24h = int(stats.get("count") or 0)
            avg = indicators.avg_24h
            if avg:
                indicators.volatility_pct = (indicators.std_24h or 0.0) / avg * 100

        indicators.ma5 = snapshot.ma(5)
        indicators.ma10 = snapshot.ma(10)
        indicators.ma20 = snapshot.ma(20)

        trend_6h = snapshot.trend(6) or {}
        indicators.trend_6h_slope = trend_6h.get("slope")
        indicators.trend_6h_direction = trend_6h.get("direction")

        trend_24h = snapshot.trend(24) or {}
        indicators.trend_24h_slope = trend_24h.get("slope")
        indicators.trend_24h_direction = trend_24h.get("direction")

        indicators.min_3m = snapshot.min_3m
        indicators.min_6m = snapshot.min_6m
        if indicators.min_3m:
            indicators.pct_from_3m_low = (
                (current_price - indicators.min_3m) / indicators.min_3m * 100
            )
        if indicators.min_6m:
            indicators.pct_from_6m_low = (
                (current_price - indicators.min_6m) / indicators.min_6m * 100
            )
        if indicators.min_24h:
            indicators.pct_from_24h_low = (
                (current_price - indicators.min_24h) / indicators.min_24h * 100
            )
        if indicators.max_24h:
            indicators.pct_from_24h_high = (
                (current_price - indicators.max_24h) / indicators.max_24h * 100
            )
        if (
            indicators.max_24h is not None
            and indicators.min_24h is not None
            and indicators.max_24h > indicators.min_24h
        ):
            indicators.range_position_24h = (current_price - indicators.min_24h) / (
                indicators.max_24h - indicators.min_24h
            )

        indicators.recent_prices = snapshot.prices_last_n(5)
        return indicators

    def to_dict(self) -> dict:
        """冻结进 `advice_records.evidence` 的形式"""
        data = {
            key: value
            for key, value in self.__dict__.items()
            if value is not None and value != []
        }
        for key in ("volatility_pct", "pct_from_3m_low", "pct_from_6m_low",
                    "pct_from_24h_low", "pct_from_24h_high", "range_position_24h"):
            if data.get(key) is not None:
                data[key] = round(float(data[key]), 3)
        return data


@dataclass
class PlanState:
    """单个计划的可执行状态 —— 进度 + 触发条件是否到点"""

    progress: PlanProgress
    trigger_policy: dict = field(default_factory=dict)
    last_lot_date: str | None = None
    last_lot_price: float | None = None
    days_since_last_lot: int | None = None

    @property
    def is_active(self) -> bool:
        return self.progress.status == "active"

    @property
    def has_remaining(self) -> bool:
        return self.progress.remaining_grams > 0

    def due_by_interval(self) -> bool:
        """按时间间隔到点"""
        if self.trigger_policy.get("type") != "interval":
            return False
        days = self.trigger_policy.get("days")
        if not days or self.days_since_last_lot is None:
            # 还没买过任何一批 → 视为到点（可以开始建仓）
            return self.progress.filled_tranches == 0
        return self.days_since_last_lot >= float(days)

    def due_by_drop(self, current_price: float) -> bool:
        """按跌幅到点：现价较上一次买入价下跌达到阈值"""
        if self.trigger_policy.get("type") != "drop_pct":
            return False
        pct = self.trigger_policy.get("pct")
        if not pct:
            return False
        if self.last_lot_price is None or self.last_lot_price <= 0:
            return self.progress.filled_tranches == 0
        drop_pct = (self.last_lot_price - current_price) / self.last_lot_price * 100
        return drop_pct >= float(pct)

    def next_tranche_grams(self) -> float:
        """本批建议买入克数：优先用计划的每批克数，否则按批次均分"""
        remaining = self.progress.remaining_grams
        if remaining <= 0:
            return 0.0
        tranches = max(self.progress.tranches, 1)
        per_tranche = self.progress.target_grams / tranches
        return round(min(per_tranche, remaining), 4)


@dataclass
class AdviceContext:
    """一次建议所需的全部输入"""

    symbol: str
    symbol_name: str
    indicators: MarketIndicators
    position: PositionSummary
    plans: list[PlanState] = field(default_factory=list)
    prefs: AdvicePrefs = field(default_factory=AdvicePrefs)
    at: datetime | None = None
    #: 建仓方式回测结论 —— 「一次性还是分批」的证据来源
    entry_strategy: EntryStrategyResult | None = None
    #: 复盘上下文：针对哪一笔买入、T+几
    subject_lot: dict | None = None
    review_horizon: int | None = None

    @property
    def is_review(self) -> bool:
        return self.subject_lot is not None

    @property
    def risk(self) -> RiskProfile:
        """当前生效的风险偏好档位（由 `prefs.risk_level` 解析而来）"""
        return resolve_risk(self.prefs.risk_level)

    @property
    def position_ratio_limit(self) -> float:
        """「仓位偏重」的判定线"""
        return position_ratio_limit(self.prefs)

    @property
    def current_price(self) -> float:
        return self.indicators.current_price

    @property
    def has_position(self) -> bool:
        return self.position.total_grams > 0

    @property
    def active_plan(self) -> PlanState | None:
        """有待买份额、且处于启用状态的计划（多个时取最早创建的那个）"""
        candidates = [p for p in self.plans if p.is_active and p.has_remaining]
        return candidates[0] if candidates else None

    @property
    def prefs_configured(self) -> bool:
        """是否配了总资金或目标克数 —— 决定建议能否给出「买多少克」"""
        return self.prefs.total_investable > 0 or self.prefs.target_grams > 0

    def position_ratio_pct(self) -> float | None:
        """持仓市值占总可投资金的比例"""
        if self.prefs.total_investable <= 0:
            return None
        value = self.position.market_value
        if value is None:
            return None
        return value / self.prefs.total_investable * 100

    def lot_pnl_pct(self) -> float | None:
        """复盘那笔买入自己的浮动盈亏（与整体持仓成本无关）"""
        if not self.subject_lot:
            return None
        entry = self.subject_lot.get("price_per_gram")
        if not entry or float(entry) <= 0:
            return None
        return round((self.current_price - float(entry)) / float(entry) * 100, 2)

    def to_evidence(self) -> dict:
        """冻结进 `advice_records.evidence` 的快照"""
        return {
            "market": self.indicators.to_dict(),
            "position": {
                "total_grams": self.position.total_grams,
                "total_cost": self.position.total_cost,
                "avg_cost": self.position.avg_cost,
                "latest_price": self.position.latest_price,
                "market_value": self.position.market_value,
                "unrealized_pnl": self.position.unrealized_pnl,
                "unrealized_pnl_pct": self.position.unrealized_pnl_pct,
                "lot_count": self.position.lot_count,
                "first_trade_date": self.position.first_trade_date,
                "last_trade_date": self.position.last_trade_date,
                "sale_count": self.position.sale_count,
                "total_sold_grams": self.position.total_sold_grams,
                "realized_pnl": self.position.realized_pnl,
            },
            "position_ratio_pct": self.position_ratio_pct(),
            "plans": [
                {
                    "plan_id": state.progress.plan_id,
                    "target_grams": state.progress.target_grams,
                    "filled_grams": state.progress.filled_grams,
                    "progress_pct": state.progress.progress_pct,
                    "tranches": state.progress.tranches,
                    "status": state.progress.status,
                    "trigger_policy": state.trigger_policy,
                    "days_since_last_lot": state.days_since_last_lot,
                    "last_lot_price": state.last_lot_price,
                }
                for state in self.plans
            ],
            "prefs": self.prefs.model_dump(),
            "review": (
                {
                    "subject_lot_id": self.subject_lot.get("id"),
                    "trade_date": self.subject_lot.get("trade_date"),
                    "grams": self.subject_lot.get("grams"),
                    "price_per_gram": self.subject_lot.get("price_per_gram"),
                    "horizon_days": self.review_horizon,
                    "lot_pnl_pct": self.lot_pnl_pct(),
                }
                if self.subject_lot
                else None
            ),
            "entry_strategy": (
                {
                    "sample_count": self.entry_strategy.sample_count,
                    "sufficient_data": self.entry_strategy.sufficient_data,
                    "recommended_tranches": self.entry_strategy.recommended_tranches,
                    "volatility_pct": self.entry_strategy.volatility_pct,
                    "volatility_percentile": self.entry_strategy.volatility_percentile,
                    "recommended": (
                        {
                            "method": self.entry_strategy.recommended.method,
                            "tranches": self.entry_strategy.recommended.tranches,
                            "avg_cost_diff_pct": (
                                self.entry_strategy.recommended.avg_cost_diff_pct
                            ),
                            "worst_case_pct": (
                                self.entry_strategy.recommended.worst_case_pct
                            ),
                            "win_rate_pct": (
                                self.entry_strategy.recommended.win_rate_pct
                            ),
                        }
                        if self.entry_strategy.recommended
                        else None
                    ),
                    "explanation": self.entry_strategy.explanation,
                }
                if self.entry_strategy
                else None
            ),
            "advised_at": (self.at or now()).isoformat(timespec="seconds"),
        }


def build_plan_states(
    plans_raw: list[dict],
    progress: list[PlanProgress],
    lots: list[dict],
    today: date,
) -> list[PlanState]:
    """把计划配置、进度与买入流水拼成可执行状态"""
    progress_by_id = {item.plan_id: item for item in progress}
    states: list[PlanState] = []
    for plan in plans_raw:
        plan_id = int(plan["id"])
        item = progress_by_id.get(plan_id)
        if item is None:  # pragma: no cover - progress 由同一批 plans 生成
            continue
        plan_lots = [lot for lot in lots if lot.get("plan_id") == plan_id]
        plan_lots.sort(key=lambda lot: (lot.get("trade_date") or "", lot.get("id") or 0))
        last = plan_lots[-1] if plan_lots else None

        days_since: int | None = None
        if last and last.get("trade_date"):
            try:
                last_date = date.fromisoformat(str(last["trade_date"]))
                days_since = (today - last_date).days
            except ValueError:  # pragma: no cover - 日期在写入时已校验
                days_since = None

        states.append(
            PlanState(
                progress=item,
                trigger_policy=plan.get("trigger_policy") or {},
                last_lot_date=str(last["trade_date"]) if last else None,
                last_lot_price=float(last["price_per_gram"]) if last else None,
                days_since_last_lot=days_since,
            )
        )
    return states
