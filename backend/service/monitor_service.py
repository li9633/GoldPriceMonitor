import time

from mapper.price_mapper import PriceMapper
from models.advice import AdviceStatus
from service.advice.advice_engine import AdviceEngine, ComputedAdvice
from service.history_import_service import init_historical_data
from service.notification_service import NotificationService
from service.price_service import PriceService
from service.send_gate import GateDecision, SendGate
from service.system_settings_service import SystemSettingsService
from service.triggers import (
    AdviceTrigger,
    DailyDigestTrigger,
    FollowupTrigger,
    ReopenGapTrigger,
    TickContext,
    TriggerOutcome,
    TriggerRegistry,
    VolatilityTrigger,
)
from utils.due_timer import DueTimer
from utils.logger import cleanup_old_logs, get_log_size, get_logger
from utils.market_session import SendPolicy
from utils.time_utils import now

#: 配置热更新间隔（秒）
SETTINGS_REFRESH_SECONDS = 60.0
#: 建议回访价格回填间隔（秒）。回访档位是 T+1/T+7/T+30，小时级完全够用；
#: 真正的到期判定是按「建议发出时间 + N 天」算的，所以间隔大小不影响正确性。
REVIEW_REFRESH_SECONDS = 3600.0
#: 日志清理间隔（秒）
LOG_CLEANUP_SECONDS = 86400.0
#: 买入后 T+n 复盘的检查间隔（秒）。触发条件按「买入日期 + N 天」判定，
#: 所以间隔大小不影响是否会漏 —— 只影响最迟多久被发现。
FOLLOWUP_REVIEW_SECONDS = 3600.0


class MonitorService:
    def __init__(self):
        self.logger = get_logger("GoldPriceMonitor")
        self.settings = SystemSettingsService()
        self.price_mapper = PriceMapper()
        self.price_service = PriceService()
        self.notification_service = NotificationService()
        # 规则在 signals / strategies，LLM 只负责措辞
        self.advice_engine = AdviceEngine()
        self.send_gate = SendGate()
        # 通知触发器：谁动了才发；评估逻辑在 triggers/，本类只做闸门与投递
        self.advice_trigger = AdviceTrigger(self.advice_engine)
        self.followup_trigger = FollowupTrigger(
            self.advice_engine, self.price_mapper, FOLLOWUP_REVIEW_SECONDS
        )
        self.volatility_trigger = VolatilityTrigger(self.settings)
        self.digest_trigger = DailyDigestTrigger(
            self.settings, self.price_mapper, self.advice_engine.portfolio_mapper
        )
        self.reopen_gap_trigger = ReopenGapTrigger(
            self.settings, self.price_mapper, self.advice_engine.portfolio_mapper
        )
        self.trigger_registry = TriggerRegistry(
            [
                self.advice_trigger,
                self.followup_trigger,
                self.volatility_trigger,
                self.digest_trigger,
                self.reopen_gap_trigger,
            ]
        )
        self.start_time = now()
        self.check_count = 0
        self.alert_count = 0
        self._last_suppressed: str | None = None

        # 定时任务统一用 DueTimer，不再各自维护 _last_xxx 时间戳
        self._settings_timer = DueTimer("设置刷新", SETTINGS_REFRESH_SECONDS)
        self._review_timer = DueTimer("回访价格回填", REVIEW_REFRESH_SECONDS)
        self._cleanup_timer = DueTimer("日志清理", LOG_CLEANUP_SECONDS)

        self._refresh_settings()

    def _refresh_settings(self) -> None:
        monitor_config = self.settings.get_monitor_config()
        self.main_symbol = monitor_config.get("main_symbol", "gds_AUTD")
        self.monitor_symbols = monitor_config.get(
            "monitor_symbols", ["gds_AUTD", "hf_XAU"]
        )
        self.check_interval = monitor_config.get("check_interval", 10)

        ai_config = self.settings.get_ai_config()
        self.ai_check_interval_minutes = ai_config.get("check_interval_minutes", 5)
        self.advice_trigger.set_interval(self.ai_check_interval_minutes * 60)

        self._settings_timer.mark(now())

    def run(self) -> None:
        self._print_banner()
        self._init_historical_data()
        self._init_modules()
        self._show_db_status()

        self.logger.info("=" * 50)
        self.logger.info("开始实时监控...\n")

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                self.logger.info("\n程序被用户中断")
                break
            except Exception as e:
                self.logger.error(f"主循环发生错误：{e}", exc_info=e)

            time.sleep(self.check_interval)

    def _print_banner(self) -> None:
        self.logger.info("=" * 50)
        self.logger.info("黄金价格智能监控系统启动")
        self.logger.info("=" * 50)

    def _init_historical_data(self) -> None:
        self.logger.info("正在初始化历史数据...")
        init_historical_data()

    def _init_modules(self) -> None:
        self.logger.info(
            f"监控配置 main_symbol={self.main_symbol} "
            f"symbols={','.join(self.monitor_symbols)} "
            f"check_interval={self.check_interval}s "
            f"ai_interval={self.ai_check_interval_minutes}min"
        )

    def _show_db_status(self) -> None:
        try:
            db_count = self.price_mapper.get_record_count(self.main_symbol)
            self.logger.info(f"历史记录数 symbol={self.main_symbol} count={db_count}")
        except Exception as e:
            self.logger.error(f"启动时查询历史记录数失败 symbol={self.main_symbol}: {e}", exc_info=e)

    def _tick(self) -> None:
        self._refresh_settings_if_needed()

        prices_data = self.price_service.fetch_all_gold_prices(self.monitor_symbols)

        main_symbol_data = prices_data.get(self.main_symbol)
        if not main_symbol_data:
            self.logger.warning(
                f"主品种价格缺失，跳过本轮 symbol={self.main_symbol}"
            )
            self.check_count += 1
            return

        current_price = main_symbol_data["price"]
        self.logger.debug(
            f"tick 价格 symbol={self.main_symbol} price={current_price} "
            f"intl={prices_data.get('hf_XAU', {}).get('price')}"
        )

        self._save_prices(prices_data, current_price)

        # 时段闸门：每个巡检周期只判断一次
        decision = self.send_gate.policy_decision()
        self._advise(prices_data, current_price, decision)
        self._run_followups(prices_data, decision)
        self._refresh_reviews_if_due()
        self._log_statistics()
        self._cleanup_logs()

        self.check_count += 1

    def _save_prices(self, prices_data: dict, current_price: float) -> None:
        self.price_mapper.save_price(self.main_symbol, current_price)
        london_data = prices_data.get("hf_XAU")
        if london_data:
            self.price_mapper.save_price("hf_XAU", london_data["price"])

    # ==================== 建议 ====================

    def _tick_context(
        self,
        prices_data: dict,
        decision: GateDecision,
        current_price: float | None = None,
    ) -> TickContext:
        london = prices_data.get("hf_XAU") or {}
        market_symbol, valuation_note = self._market_view(prices_data, decision)
        if market_symbol:
            # INTL_ONLY：SGE 价格冻结，口径价切到国际金折算价
            market_price = float(london["converted_cny_price"])
        elif current_price is not None:
            market_price = current_price
        else:
            main = prices_data.get(self.main_symbol) or {}
            market_price = float(main.get("price") or 0.0)
        return TickContext(
            at=now(),
            decision=decision,
            prices_data=prices_data,
            main_symbol=self.main_symbol,
            market_symbol=market_symbol,
            market_price=market_price,
            london_cny=london.get("converted_cny_price"),
            london_usd=london.get("price"),
            valuation_note=valuation_note,
        )

    def _advise(
        self, prices_data: dict, current_price: float, decision: GateDecision
    ) -> None:
        """生成建议并按闸门决定是否推送。

        兼容入口：评估逻辑在 `AdviceTrigger`，这里只做闸门、落库与投递。
        """
        # 时段闸门：休市静默 —— 不生成建议、也不调用 AI
        if not decision.allowed:
            self._note_suppressed("建议", decision.reason, decision.detail)
            return
        outcome = self.advice_trigger.evaluate(
            self._tick_context(prices_data, decision, current_price)
        )
        self._handle_outcome(outcome, decision)

    @staticmethod
    def _market_view(
        prices_data: dict, decision: GateDecision
    ) -> tuple[str | None, str]:
        """决定本轮建议的行情口径。

        INTL_ONLY（SGE 休市、国际金开市）且有国际金折算价时，建议的指标与
        估值价来自国际金（主体仍是 SGE 品种），消息中注明可能有计算误差。
        返回 `(口径品种, 估值说明)`；正常时段返回 `(None, "")`。
        """
        if decision.policy is not SendPolicy.INTL_ONLY:
            return None, ""
        london = prices_data.get("hf_XAU") or {}
        if not london.get("converted_cny_price"):
            return None, ""
        return "hf_XAU", "休市期间以国际金折算价估算，可能与国内开盘价存在偏差"

    def _suppress(self, computed: ComputedAdvice, reason: str, detail: str) -> None:
        """被抑制的建议也落库（标记 suppressed），这样「当时为什么没发」以后查得到"""
        self.advice_engine.save(
            computed, status=AdviceStatus.SUPPRESSED.value, suppressed_reason=reason
        )
        self._note_suppressed("推送", reason, detail)

    # ==================== 买入后 T+n 复盘 ====================

    def _run_followups(self, prices_data: dict, decision: GateDecision) -> None:
        """为到点的买入生成复盘建议（T+1 / T+7 / T+30）。兼容入口。"""
        outcome = self.followup_trigger.evaluate(
            self._tick_context(prices_data, decision)
        )
        self._handle_outcome(outcome, decision)

    # ==================== 事件执行（终审闸门 + 落库 + 投递） ====================

    def _handle_outcome(
        self, outcome: TriggerOutcome, decision: GateDecision
    ) -> None:
        """触发器产出的候选事件统一过终审闸门，再落库 / 投递。"""
        for sup in outcome.suppressed:
            if sup.computed is not None:
                self._suppress(sup.computed, sup.reason, sup.detail)
            else:
                self._note_suppressed(sup.source, sup.reason, sup.detail)

        for ev in outcome.events:
            send_decision = self.send_gate.review(
                decision,
                key=ev.dedup_key,
                price=ev.price_basis,
                urgency=ev.urgency,
                cooldown_minutes=ev.cooldown_minutes,
            )
            if not send_decision.allowed:
                if ev.computed is not None and ev.save_suppressed:
                    self._suppress(
                        ev.computed, send_decision.reason, send_decision.detail
                    )
                else:
                    self.logger.debug(
                        f"事件被闸门拦下 kind={ev.kind} reason={send_decision.reason} "
                        f"detail={send_decision.detail}"
                    )
                continue

            if ev.computed is not None:
                record = self.advice_engine.save(ev.computed)
                if self.notification_service.send_advice(
                    record, ev.current_price, extra_info=ev.extra_info or None
                ):
                    self.alert_count += 1
                    self._clear_suppressed()
                    self.logger.info(
                        f"建议已投递 kind={ev.kind} advice_id={record.id} "
                        f"action={record.action.value} price={ev.current_price}"
                    )
                else:
                    self.logger.warning(
                        f"建议投递失败（无渠道成功） advice_id={record.id} "
                        f"action={record.action.value}"
                    )
            elif ev.notification is not None:
                if self.notification_service.send(ev.notification):
                    self.alert_count += 1
                    self._clear_suppressed()
                else:
                    self.logger.warning(
                        f"通知投递失败（无渠道成功） kind={ev.kind} "
                        f"dedup_key={ev.dedup_key}"
                    )

    def _refresh_reviews_if_due(self) -> None:
        """定期回填 T+1/T+7/T+30 的回访价格。

        这是「建议准不准」这组数据能否**自动**积累的关键 —— 在此之前只能靠手动调
        `/advice/reviews/refresh`，实际上就没人会去调。

        刻意放在时段闸门之外：回填读的是历史价格，与当前是否休市无关，
        周末/节假日反而正是补齐回访的好时机。
        """
        at = now()
        if not self._review_timer.is_due(at):
            return
        self._review_timer.mark(at)
        try:
            result = self.advice_engine.refresh_reviews(at)
        except Exception as exc:
            self.logger.error(f"回访价格回填失败：{exc}", exc_info=exc)
            return
        if result["filled"] or result["skipped"]:
            self.logger.info(
                f"回访价格回填：检查 {result['checked']} 条，"
                f"成功 {result['filled']} 条，缺价跳过 {result['skipped']} 条"
            )

    def _refresh_settings_if_needed(self) -> None:
        at = now()
        if not self._settings_timer.is_due(at):
            return
        self._settings_timer.mark(at)
        self._refresh_settings()

    def _note_suppressed(self, source: str, reason: str, detail: str) -> None:
        """记录被抑制的原因。

        同一原因只在首次记 INFO，重复时降为 DEBUG —— 静默期可能持续整个周末，
        否则日志会被刷屏，真正的原因反而看不见。
        """
        signature = f"{source}:{reason}"
        if self._last_suppressed == signature:
            self.logger.debug(
                f"持续抑制 source={source} reason={reason} detail={detail}"
            )
            return
        self._last_suppressed = signature
        self.logger.info(f"通知已抑制 source={source} reason={reason} detail={detail}")

    def _clear_suppressed(self) -> None:
        self._last_suppressed = None

    def _log_statistics(self) -> None:
        if self.check_count % 100 != 0:
            return
        run_time = (now() - self.start_time).total_seconds() / 60
        self.logger.info(
            f"运行统计 runtime_min={run_time:.1f} checks={self.check_count} "
            f"alerts={self.alert_count} log_kb={get_log_size() / 1024:.0f}"
        )

    def _cleanup_logs(self) -> None:
        at = now()
        if not self._cleanup_timer.is_due(at):
            return
        self._cleanup_timer.mark(at)
        log_config = self.settings.get_log_config()
        keep_days = log_config.get("keep_days", 30) if log_config else 30
        cleanup_old_logs(keep_days)
