"""买入复盘触发器 —— 迁移自 `MonitorService._run_followups / _dispatch_followup`。

为到点的买入生成 T+1 / T+7 / T+30 复盘。复盘是「一次性事件」，靠 `has_review`
保证不重复；被闸门拦下时**刻意不落库**（落库会让 has_review 变真，复盘就丢了），
下一次巡检（仍在追补窗口内）会重试 —— 对应 `Suppression.computed is None`。
"""

from service.triggers.base import (
    ADVICE_COOLDOWN_MINUTES,
    KIND_REVIEW,
    NotificationEvent,
    Suppression,
    TickContext,
    Trigger,
    TriggerOutcome,
)
from utils.due_timer import DueTimer
from utils.logger import get_logger

logger = get_logger("FollowupTrigger")

#: 单次巡检最多生成几条复盘，避免首次上线时对历史买入集中补发
MAX_FOLLOWUPS_PER_TICK = 3


class FollowupTrigger(Trigger):
    def __init__(
        self,
        engine,
        price_mapper,
        interval_seconds: float = 3600.0,
    ) -> None:
        self.engine = engine
        #: 取价兜底用监控循环的 price_mapper（历史行为：优先 tick 数据，其次库中最新价）
        self.price_mapper = price_mapper
        self._timer = DueTimer("买入复盘", interval_seconds)

    @property
    def name(self) -> str:
        return "followup"

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        if not self._timer.is_due(tick.at):
            return TriggerOutcome()
        self._timer.mark(tick.at)

        # 休市静默期不生成：复盘的内容依赖当前价格，闭市时价格是冻结的，
        # 生成出来也只能说「观望」。留到开市后再做。
        if not tick.decision.allowed:
            return TriggerOutcome(
                suppressed=[
                    Suppression(
                        source="买入复盘",
                        reason=tick.decision.reason,
                        detail=tick.decision.detail,
                    )
                ]
            )

        try:
            pending = self.engine.pending_reviews(tick.at)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"查询待复盘买入失败：{exc}", exc_info=exc)
            return TriggerOutcome()

        if not pending:
            return TriggerOutcome()

        logger.info(f"发现 {len(pending)} 条待复盘买入，本次处理前 {MAX_FOLLOWUPS_PER_TICK} 条")
        outcome = TriggerOutcome()
        for lot, horizon in pending[:MAX_FOLLOWUPS_PER_TICK]:
            self._evaluate_lot(tick, lot, horizon, outcome)
        return outcome

    def _evaluate_lot(self, tick: TickContext, lot: dict, horizon: int, outcome: TriggerOutcome) -> None:
        symbol = lot.get("symbol")
        if not symbol:
            logger.warning(
                f"买入记录 id={lot.get('id')} 缺少 symbol，跳过 T+{horizon} 复盘"
            )
            return
        symbol = str(symbol)
        price = self._price_for(symbol, tick.prices_data)
        if price is None:
            logger.warning(f"品种 {symbol} 没有可用价格，跳过 T+{horizon} 复盘")
            return

        # 复盘的盈亏对比按开市市场估值（INTL_ONLY 时为国际金折算价）
        market_price = tick.market_price if tick.market_symbol else price

        computed = self.engine.compute(
            symbol,
            market_price,
            tick.london_cny,
            tick.london_usd,
            market_symbol=tick.market_symbol,
            subject_lot=lot,
            review_horizon=horizon,
        )

        from models.advice import ACTION_URGENCY

        urgency = ACTION_URGENCY.get(computed.draft.action.value, "low")
        extra_info: dict = {}
        if tick.london_cny is not None:
            extra_info["london_gold_usd"] = tick.london_usd
            extra_info["london_gold_cny"] = tick.london_cny
        if computed.model_info:
            extra_info["ai_model_info"] = computed.model_info
        if tick.valuation_note:
            extra_info["valuation_note"] = tick.valuation_note

        outcome.events.append(
            NotificationEvent(
                kind=KIND_REVIEW,
                symbol=symbol,
                dedup_key=f"{symbol}#review#{lot.get('id')}#{horizon}",
                urgency=urgency,
                cooldown_minutes=ADVICE_COOLDOWN_MINUTES,
                price_basis=market_price,
                current_price=market_price,
                computed=computed,
                extra_info=extra_info,
                save_suppressed=False,
            )
        )

    def _price_for(self, symbol: str, prices_data: dict) -> float | None:
        """优先用本轮刚抓到的价格，其次回落到库中最新价"""
        data = prices_data.get(symbol) or {}
        if data.get("price"):
            return float(data["price"])
        return self.price_mapper.get_latest_price(symbol)
