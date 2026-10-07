"""波动事件触发器 —— 价格较基准移动 ≥ 阈值时即时提醒。

双基准取偏离大者：上次提醒价（保证连续感知）与节前 SGE 收盘价（保证长假首日
必有感知）。两档：≥1% 提醒（受冷却限制）、≥2.5% 强提醒（不受冷却限制）。
阈值全部来自 advice_config（volatility_*），可在设置页调整。

level 2 去噪：强提醒虽不受冷却限制，但价格在阈值附近**徘徊**时（如假期内
国际金持续停在 -2.6% 附近，每个 tick 都满足 ≥2.5%）会每 10 秒刷一条。
因此 level 2 重发需满足「偏离较上次强提醒加深 ≥ LEVEL2_RETRIGGER_PCT
或方向反转」——恶化即时知晓，横盘不再刷屏。
"""

from datetime import datetime

from channels.base import KIND_VOLATILITY, NotificationData
from service.triggers.base import (
    NotificationEvent,
    TickContext,
    Trigger,
    TriggerOutcome,
)
from service.triggers.notify_common import (
    fmt_pct,
    pct_change,
    trigger_config,
)
from utils.logger import get_logger

logger = get_logger("VolatilityTrigger")

#: level 2 重发门槛（百分点）：偏离较上次强提醒加深达到该值才重发
LEVEL2_RETRIGGER_PCT = 0.5


class VolatilityTrigger(Trigger):
    def __init__(self, settings) -> None:
        self.settings = settings
        # 口径品种 → 基线价格（首个 tick 以当时价格建立基线）
        self._baseline: dict[str, float] = {}
        # 口径品种 → 上次提醒时间（level 1 冷却用）
        self._last_emitted: dict[str, datetime] = {}
        # 口径品种 → 上次强提醒时的带符号偏离（level 2 去噪用）
        self._last_emitted_move: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "volatility"

    def evaluate(self, tick: TickContext) -> TriggerOutcome:
        config = trigger_config(self.settings)
        if not config["volatility_enabled"] or not tick.decision.allowed:
            return TriggerOutcome()
        price = tick.market_price
        if price <= 0:
            return TriggerOutcome()

        key = tick.market_symbol or tick.main_symbol
        baseline = self._baseline.setdefault(key, price)

        # 双基准取偏离大者
        candidates: list[tuple[str, float]] = [("较上次提醒", baseline)]
        sge_close = self._sge_close(tick)
        if sge_close and sge_close > 0:
            candidates.append(("较节前收盘", sge_close))
        label, base = max(
            candidates, key=lambda c: abs(pct_change(price, c[1]) or 0.0)
        )
        move = pct_change(price, base)

        trigger_pct = max(float(config["volatility_trigger_pct"]), 0.1)
        critical_pct = max(float(config["volatility_critical_pct"]), trigger_pct)
        level = 2 if abs(move or 0) >= critical_pct else (
            1 if abs(move or 0) >= trigger_pct else 0
        )
        if level == 0:
            return TriggerOutcome()

        cooldown_minutes = float(config["volatility_cooldown_minutes"])
        last_emitted = self._last_emitted.get(key)
        if (
            level == 1
            and last_emitted is not None
            and (tick.at - last_emitted).total_seconds() < cooldown_minutes * 60
        ):
            return TriggerOutcome()

        move_val = move or 0.0
        if level == 2:
            # 强提醒去噪：偏离较上次强提醒加深 ≥ 门槛（或方向反转）才重发；
            # 首次触发（无上次记录）必然发出
            last_move = self._last_emitted_move.get(key)
            if last_move is not None:
                deepened = abs(move_val) - abs(last_move) >= LEVEL2_RETRIGGER_PCT
                flipped = (move_val > 0) != (last_move > 0)
                if not (deepened or flipped):
                    logger.debug(
                        f"[{key}] 偏离仍在 {fmt_pct(move_val)}（较上次 "
                        f"{fmt_pct(last_move)} 未加深），跳过强提醒"
                    )
                    return TriggerOutcome()

        if move_val > 0:
            direction = "上涨"
        elif move_val < 0:
            direction = "下跌"
        else:
            direction = "持平"
        symbol_name = self.settings.get_symbol_name_map().get(key, key)
        # 「当前价格」由通用模板的固定行展示，不放进 fields（避免重复渲染）
        fields = {
            label: fmt_pct(move),
        }
        if tick.london_usd and tick.london_usd > 0:
            fields["国际金"] = f"${tick.london_usd:.2f}"
        if tick.market_symbol:
            fields["口径"] = "国际金折算价" + (
                f"（{tick.valuation_note}）" if tick.valuation_note else ""
            )

        event = NotificationEvent(
            kind=KIND_VOLATILITY,
            symbol=key,
            # level 2 不受去重冷却限制（cooldown 0 → 立即放行）
            cooldown_minutes=0.0 if level == 2 else cooldown_minutes,
            urgency="high" if level == 2 else "medium",
            dedup_key=f"{key}#volatility",
            price_basis=price,
            current_price=price,
            summary=f"黄金{direction} {fmt_pct(move)}",
            notification=NotificationData(
                kind=KIND_VOLATILITY,
                symbol=key,
                symbol_name=symbol_name,
                current_price=price,
                fields=fields,
                alert_level="critical" if level == 2 else "warning",
                summary=f"黄金{direction} {fmt_pct(move)}",
            ),
        )
        # 基线与冷却状态随提醒推进；强提醒额外记录带符号偏离供去噪比较
        self._baseline[key] = price
        self._last_emitted[key] = tick.at
        if level == 2:
            self._last_emitted_move[key] = move_val
        logger.info(
            f"[{key}] {direction} {fmt_pct(move)}（level {level}）→ 推送波动提醒"
        )
        return TriggerOutcome(events=[event])

    @staticmethod
    def _sge_close(tick: TickContext) -> float | None:
        """节前 SGE 收盘价：INTL_ONLY 期间主品种价格冻结，即为节前收盘"""
        main = tick.prices_data.get(tick.main_symbol) or {}
        price = main.get("price")
        return float(price) if price else None
