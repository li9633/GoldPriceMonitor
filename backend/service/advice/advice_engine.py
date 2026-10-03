"""建议引擎 —— 编排「上下文 → 信号 → 策略 → 措辞 → 落库」。

给定行情与用户的持仓/计划/偏好，产出一条结构化、可回溯的建议。

`generate()` 刻意接受调用方传入的价格，这样 `MonitorService` 可以直接把实时抓到的
价格传进来，不必为了生成建议再发一次网络请求。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from mapper.advice_mapper import REVIEW_HORIZONS, AdviceMapper
from mapper.portfolio_mapper import PortfolioMapper
from mapper.price_mapper import PriceMapper
from models.advice import (
    AdviceDraft,
    AdviceKind,
    AdviceNowResponse,
    AdvicePrefs,
    AdviceRecord,
    AdviceReviewStats,
    AdviceStatus,
)
from models.portfolio import PositionSummary
from service.advice import signals as signal_rules
from service.advice.advisor import AdviceAdvisor
from service.advice.context import (
    AdviceContext,
    MarketIndicators,
    build_plan_states,
)
from service.advice.entry_strategy import EntryStrategyEvaluator
from service.advice.strategies import build_advice, select_kind
from service.position import compute_position, summarize_plans
from service.price_service import PriceService
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger
from utils.time_utils import CHINA_TZ, now, today

logger = get_logger("AdviceEngine")

#: 买入后的复盘档位（天）
FOLLOWUP_HORIZONS = (1, 7, 30)
#: 追补窗口：距买入 N 天后仍在此窗口内才补做复盘
FOLLOWUP_CATCHUP_DAYS = 2


@dataclass
class ComputedAdvice:
    """算好但尚未落库的建议"""

    draft: AdviceDraft
    rationale: str
    model_info: str
    price: float
    subject_lot_id: int | None = None
    review_horizon: int | None = None


class AdviceEngine:
    """建议生成与查询"""

    def __init__(self) -> None:
        self.settings = SystemSettingsService()
        self.price_mapper = PriceMapper()
        self.portfolio_mapper = PortfolioMapper()
        self.advice_mapper = AdviceMapper()
        self.price_service = PriceService()
        self.advisor = AdviceAdvisor()
        self.entry_evaluator = EntryStrategyEvaluator(self.price_mapper)

    # ==================== 配置 ====================

    def get_prefs(self) -> AdvicePrefs:
        config = self.settings.get_advice_config() or {}
        alert_config = self.settings.get_alert_config() or {}
        return AdvicePrefs(
            total_investable=float(config.get("total_investable") or 0.0),
            target_grams=float(config.get("target_grams") or 0.0),
            target_position_ratio=float(config.get("target_position_ratio") or 0.0),
            risk_level=str(config.get("risk_level") or "balanced"),
            absolute_low_price=float(alert_config.get("absolute_low_price") or 0.0),
            absolute_alert_enabled=bool(alert_config.get("enable_absolute_alert", True)),
            enable_llm=bool(config.get("enable_llm", True)),
        )

    def price_move_trigger_pct(self) -> float:
        """推送节流阈值：价格偏离上次建议超过该比例才值得再推一条"""
        config = self.settings.get_advice_config() or {}
        return float(config.get("price_move_trigger_pct") or 0.0)

    def main_symbol(self) -> str:
        return self.settings.get_monitor_config().get("main_symbol") or "gds_AUTD"

    # ==================== 取价 ====================

    def resolve_price(self, symbol: str) -> tuple[float | None, str]:
        """优先实时价，失败回落到库里最新价。

        返回 `(价格, 来源)`，来源为 `live` / `stored` / `none`。
        """
        try:
            live = self.price_service.fetch_current_price(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取 %s 实时价失败：%s", symbol, exc)
            live = None
        if live and live.get("price"):
            return float(live["price"]), "live"
        stored = self.price_mapper.get_latest_price(symbol)
        if stored is not None:
            return float(stored), "stored"
        return None, "none"

    # ==================== 生成 ====================

    def compute(
        self,
        symbol: str,
        current_price: float,
        london_cny: float | None = None,
        london_usd: float | None = None,
        *,
        use_llm: bool | None = None,
        subject_lot: dict | None = None,
        review_horizon: int | None = None,
    ) -> ComputedAdvice:
        """算出建议但**不落库**。

        监控循环需要「先算出来、判断值不值得推、再决定以什么状态落库」，所以把
        计算与持久化分开。`generate()` 是二者的便捷组合。

        传入 `subject_lot` + `review_horizon` 时产出的是**复盘**建议
        （针对某笔买入的 T+n 回访）。
        """
        ctx = self.build_context(
            symbol,
            current_price,
            london_cny,
            london_usd,
            subject_lot=subject_lot,
            review_horizon=review_horizon,
        )
        found = signal_rules.evaluate(ctx)
        draft = build_advice(ctx, found)

        want_llm = ctx.prefs.enable_llm if use_llm is None else use_llm
        rationale, model_info = draft.rationale, ""
        if want_llm:
            rationale, model_info = self.advisor.phrase(ctx, draft)

        return ComputedAdvice(
            draft=draft,
            rationale=rationale,
            model_info=model_info,
            price=current_price,
            subject_lot_id=(subject_lot or {}).get("id"),
            review_horizon=review_horizon,
        )

    @staticmethod
    def _record_dict(
        computed: ComputedAdvice, status: str, suppressed_reason: str
    ) -> dict:
        draft = computed.draft
        return {
            "kind": draft.kind.value,
            "action": draft.action.value,
            "symbol": draft.symbol,
            "target_grams": draft.target_grams,
            "price_band_low": draft.price_band_low,
            "price_band_high": draft.price_band_high,
            "confidence": draft.confidence,
            "rationale": computed.rationale,
            "signals": [s.model_dump(mode="json") for s in draft.signals],
            "evidence": draft.evidence,
            "model_info": computed.model_info,
            "status": status,
            "suppressed_reason": suppressed_reason,
            "price_at_advice": computed.price,
            "subject_lot_id": computed.subject_lot_id,
            "review_horizon": computed.review_horizon,
        }

    def save(
        self,
        computed: ComputedAdvice,
        *,
        status: str = AdviceStatus.DELIVERED.value,
        suppressed_reason: str = "",
    ) -> AdviceRecord:
        """把算好的建议落库。被闸门抑制的也落库，只是标记 `suppressed` ——
        这样「当时为什么没发」以后查得到。"""
        advice_id = self.advice_mapper.insert_advice(
            self._record_dict(computed, status, suppressed_reason)
        )
        stored = self.advice_mapper.get_advice(advice_id)
        if stored is None:  # pragma: no cover
            raise RuntimeError("建议写入失败")
        return AdviceRecord(**stored)

    def generate(
        self,
        symbol: str,
        current_price: float,
        london_cny: float | None = None,
        london_usd: float | None = None,
        *,
        persist: bool = True,
        use_llm: bool | None = None,
    ) -> AdviceRecord:
        """算出一条建议；`persist=False` 时只算不落库（用于预览）"""
        computed = self.compute(
            symbol, current_price, london_cny, london_usd, use_llm=use_llm
        )
        if not persist:
            payload = self._record_dict(
                computed, AdviceStatus.DELIVERED.value, ""
            )
            payload["id"] = 0
            payload["created_at"] = ""
            return AdviceRecord(**payload)
        return self.save(computed)

    def last_pushed(self, symbol: str) -> AdviceRecord | None:
        row = self.advice_mapper.last_pushed(symbol)
        return AdviceRecord(**row) if row else None

    # ==================== 买入后的 T+n 复盘 ====================

    def pending_reviews(self, at: datetime | None = None) -> list[tuple[dict, int]]:
        """找出该做复盘但还没做的「买入 × 档位」。

        触发条件是 `距今 == T+n`（含 `FOLLOWUP_CATCHUP_DAYS` 天追补窗口），
        不是 `距今 >= T+n` —— 否则补录一笔历史买入会被一次性补出三条复盘。

        `has_review` 只认非 suppressed 的记录，所以被闸门拦下的复盘会重试。
        「期初持仓」不参与回访。
        """
        reference = at or now()
        today = reference.date()
        pending: list[tuple[dict, int]] = []
        for lot in self.portfolio_mapper.list_lots():
            if lot.get("is_opening"):
                continue
            try:
                trade_date = date.fromisoformat(str(lot.get("trade_date")))
            except (ValueError, TypeError):
                logger.warning("买入记录 %s 的日期无法解析，跳过复盘", lot.get("id"))
                continue
            age = (today - trade_date).days
            for horizon in FOLLOWUP_HORIZONS:
                if not (horizon <= age <= horizon + FOLLOWUP_CATCHUP_DAYS):
                    continue
                if self.advice_mapper.has_review(int(lot["id"]), horizon):
                    continue
                pending.append((lot, horizon))
        return pending

    def generate_review(
        self,
        lot: dict,
        horizon: int,
        current_price: float,
        *,
        london_cny: float | None = None,
        london_usd: float | None = None,
        persist: bool = True,
        use_llm: bool | None = None,
    ) -> AdviceRecord:
        """为某笔买入生成 T+n 复盘建议"""
        computed = self.compute(
            str(lot.get("symbol")),
            current_price,
            london_cny,
            london_usd,
            use_llm=use_llm,
            subject_lot=lot,
            review_horizon=horizon,
        )
        if not persist:
            payload = self._record_dict(computed, AdviceStatus.DELIVERED.value, "")
            payload["id"] = 0
            payload["created_at"] = ""
            return AdviceRecord(**payload)
        return self.save(computed)

    def build_context(
        self,
        symbol: str,
        current_price: float,
        london_cny: float | None = None,
        london_usd: float | None = None,
        *,
        with_entry_strategy: bool = True,
        subject_lot: dict | None = None,
        review_horizon: int | None = None,
    ) -> AdviceContext:
        snapshot = self.price_mapper.get_check_snapshot(symbol)
        indicators = MarketIndicators.from_snapshot(
            snapshot, current_price, london_cny, london_usd
        )

        lots = self.portfolio_mapper.list_lots(symbol)
        sales = self.portfolio_mapper.list_sales(symbol)
        plans_raw = self.portfolio_mapper.list_plans(symbol)
        # 用「本次建议用的价格」算市值，保证建议与证据里的持仓口径一致；
        # 必须带上卖出记录，否则止盈止损卖出后系统仍按原持仓判断
        position = compute_position(
            symbol, lots, latest_price=current_price, sales=sales
        )
        progress = summarize_plans(plans_raw, lots)
        plan_states = build_plan_states(plans_raw, progress, lots, _today())

        entry_strategy = None
        if with_entry_strategy:
            entry_strategy = self.entry_evaluator.evaluate(symbol, current_price)

        return AdviceContext(
            symbol=symbol,
            symbol_name=self.settings.get_symbol_name_map().get(symbol, symbol),
            indicators=indicators,
            position=position,
            plans=plan_states,
            prefs=self.get_prefs(),
            entry_strategy=entry_strategy,
            subject_lot=subject_lot,
            review_horizon=review_horizon,
        )

    def now(
        self, symbol: str | None = None, use_llm: bool | None = None
    ) -> AdviceNowResponse:
        """手动请求一条建议 —— 对应「现在该不该买」这个入口"""
        target = symbol or self.main_symbol()
        price, source = self.resolve_price(target)
        if price is None:
            raise ValueError(f"品种 {target} 没有可用价格，无法生成建议")
        if source == "stored":
            logger.info("%s 使用库中最新价（实时获取失败）", target)

        london_cny, london_usd = self._resolve_london()
        record = self.generate(
            target, price, london_cny, london_usd, persist=True, use_llm=use_llm
        )
        ctx = self.build_context(target, price, london_cny, london_usd)
        return AdviceNowResponse(
            advice=record,
            symbol=target,
            current_price=price,
            position=self._position_payload(ctx.position),
            plan_progress=[
                state.progress.model_dump(mode="json") for state in ctx.plans
            ],
            prefs_configured=ctx.prefs_configured,
        )

    def _resolve_london(self) -> tuple[float | None, float | None]:
        """伦敦金参考价，失败不影响主流程"""
        try:
            data = self.price_service.fetch_current_price("hf_XAU")
        except Exception:  # noqa: BLE001
            return None, None
        if not data:
            return None, None
        return data.get("converted_cny_price"), data.get("price")

    @staticmethod
    def _position_payload(position: PositionSummary) -> dict:
        return position.model_dump(mode="json")

    # ==================== 查询与生命周期 ====================

    def history(
        self,
        symbol: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdviceRecord]:
        rows = self.advice_mapper.list_advice(symbol, kind, status, limit, offset)
        return [AdviceRecord(**row) for row in rows]

    def count(
        self, symbol: str | None = None, kind: str | None = None, status: str | None = None
    ) -> int:
        return self.advice_mapper.count_advice(symbol, kind, status)

    def get(self, advice_id: int) -> AdviceRecord | None:
        row = self.advice_mapper.get_advice(advice_id)
        return AdviceRecord(**row) if row else None

    def mark_acknowledged(self, advice_id: int) -> bool:
        if self.advice_mapper.get_advice(advice_id) is None:
            return False
        return self.advice_mapper.update_status(advice_id, "acknowledged")

    def mark_acted(self, advice_id: int, lot_id: int | None = None) -> bool:
        """记录「我照做了」—— 评估建议有效性的基础"""
        if self.advice_mapper.get_advice(advice_id) is None:
            return False
        return self.advice_mapper.update_status(advice_id, "acted", lot_id)

    # ==================== 有效性回访 ====================

    def refresh_reviews(self, at: datetime | None = None) -> dict:
        """回填到期的 T+1 / T+7 / T+30 价格。

        **回填的是「目标日期当时」的价格**（`get_price_near`），不是「现在」的价格。
        否则停机几天后再回填，T+1 会被写成 T+5 的价格 —— 这种错误不报错，
        只会静默污染「建议准不准」的统计。

        建议有效性是长期唯一的护城河，所以这组数据从第一天就开始积累。
        """
        reference = at or now()
        checked = filled = skipped = 0
        for horizon in REVIEW_HORIZONS:
            for record in self.advice_mapper.list_pending_reviews(horizon, reference):
                checked += 1
                target_ts = _review_target_timestamp(record["created_at"], horizon)
                price = (
                    self.price_mapper.get_price_near(record["symbol"], target_ts)
                    if target_ts is not None
                    else None
                )
                if price is None:
                    skipped += 1
                    logger.debug(
                        "建议 %s 的 T+%d 缺少对应时点的价格，跳过",
                        record.get("id"),
                        horizon,
                    )
                    continue
                if self.advice_mapper.update_review_prices(
                    record["id"], f"price_t{horizon}", price
                ):
                    filled += 1
        if filled or skipped:
            logger.info(
                "回访价格回填：检查 %d，成功 %d，缺价跳过 %d", checked, filled, skipped
            )
        return {"checked": checked, "filled": filled, "skipped": skipped}

    def review_stats(self) -> AdviceReviewStats:
        return AdviceReviewStats(**self.advice_mapper.review_stats())

    # ==================== 供 MonitorService 使用 ====================

    def planned_kind(self, symbol: str, current_price: float) -> AdviceKind:
        """不落库地判断当前会走哪套策略（给监控循环做日志用）"""
        ctx = self.build_context(symbol, current_price)
        return select_kind(ctx)


def _today() -> date:
    return today().date()


def _review_target_timestamp(created_at: str, horizon_days: int) -> int | None:
    """建议发出时间 + N 天 → 目标时点的 Unix 时间戳。

    `created_at` 由 `now_str()` 写成北京时间字符串；解析失败返回 `None`
    （宁可跳过，也不要拿一个错误的时点去取价）。
    """
    try:
        base = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=CHINA_TZ
        )
    except (ValueError, TypeError):
        logger.warning("建议的 created_at 无法解析：%r", created_at)
        return None
    return int((base + timedelta(days=horizon_days)).timestamp())
