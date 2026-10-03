import time

from mapper.price_mapper import PriceMapper
from models.advice import ACTION_URGENCY, AdviceStatus
from service.advice.advice_engine import AdviceEngine, ComputedAdvice
from service.history_import_service import init_historical_data
from service.notification_service import NotificationService
from service.price_service import PriceService
from service.send_gate import GateDecision, SendGate
from service.system_settings_service import SystemSettingsService
from utils.due_timer import DueTimer
from utils.logger import cleanup_old_logs, get_log_size, get_logger
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
#: 单次巡检最多生成几条复盘，避免首次上线时对历史买入集中补发
MAX_FOLLOWUPS_PER_TICK = 3


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
        self.start_time = now()
        self.check_count = 0
        self.alert_count = 0
        self._last_suppressed: str | None = None

        # 定时任务统一用 DueTimer，不再各自维护 _last_xxx 时间戳
        self._settings_timer = DueTimer("设置刷新", SETTINGS_REFRESH_SECONDS)
        self._advice_timer = DueTimer("建议评估", 0.0)
        self._review_timer = DueTimer("回访价格回填", REVIEW_REFRESH_SECONDS)
        self._followup_timer = DueTimer("买入复盘", FOLLOWUP_REVIEW_SECONDS)
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
        self._advice_timer.set_interval(self.ai_check_interval_minutes * 60)

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
        self.logger.info(f"监控品种：{self.main_symbol}")
        self.logger.info(f"监控品种列表：{self.monitor_symbols}")
        self.logger.info(f"检查间隔：{self.check_interval} 秒")
        self.logger.info(f"AI 分析：每 {self.ai_check_interval_minutes} 分钟调用一次")

    def _show_db_status(self) -> None:
        try:
            db_count = self.price_mapper.get_record_count(self.main_symbol)
            self.logger.info(f"当前历史记录数：{db_count} 条")
        except Exception as e:
            self.logger.error(f"查询数据库失败：{e}", exc_info=e)

    def _tick(self) -> None:
        self._refresh_settings_if_needed()

        prices_data = self.price_service.fetch_all_gold_prices(self.monitor_symbols)

        main_symbol_data = prices_data.get(self.main_symbol)
        if not main_symbol_data:
            self.logger.warning(
                f"[{now()}] 获取主品种 {self.main_symbol} 价格失败，等待下次检查"
            )
            self.check_count += 1
            return

        current_price = main_symbol_data["price"]
        self.logger.debug(
            f"[{now().strftime('%H:%M:%S')}] {main_symbol_data['name']} 价格：{current_price}"
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

    def _advise(
        self, prices_data: dict, current_price: float, decision: GateDecision
    ) -> None:
        """生成建议并按闸门决定是否推送。

        无论有没有越线都会定期评估，产出结构化建议。
        """
        # 1) 时段闸门：休市静默 —— 不生成建议、也不调用 AI
        if not decision.allowed:
            self._note_suppressed("建议", decision.reason, decision.detail)
            return

        # 2) 节流：按配置的巡检间隔重新评估
        if not self._should_advise():
            return
        self._advice_timer.mark(now())

        london_data = prices_data.get("hf_XAU") or {}
        computed = self.advice_engine.compute(
            self.main_symbol,
            current_price,
            london_data.get("converted_cny_price"),
            london_data.get("price"),
        )
        action = computed.draft.action.value
        self.logger.info(
            f"建议评估：{action}（{computed.draft.kind.value}）"
            f"置信度 {computed.draft.confidence}"
        )

        # 3) 推送节流：动作变化，或价格偏离上次推送超过阈值
        should_push, reason = self._should_push(computed, current_price)
        if not should_push:
            self._suppress(computed, reason, "动作与上次相同，且价格未明显变动")
            return

        # 4) 终审闸门：LOW_FREQ 优先级过滤 + 冷却去重
        urgency = ACTION_URGENCY.get(action, "low")
        send_decision = self.send_gate.review(
            decision,
            key=f"{self.main_symbol}#advice#{action}",
            price=current_price,
            urgency=urgency,
        )
        if not send_decision.allowed:
            self._suppress(computed, send_decision.reason, send_decision.detail)
            return

        # 5) 落库并投递
        record = self.advice_engine.save(computed)
        extra_info = self._build_extra_info(prices_data, computed.model_info)
        if self.notification_service.send_advice(
            record, current_price, extra_info=extra_info
        ):
            self.alert_count += 1
            self._clear_suppressed()
        else:
            self.logger.warning("建议已生成，但没有渠道投递成功")

    def _suppress(self, computed: ComputedAdvice, reason: str, detail: str) -> None:
        """被抑制的建议也落库（标记 suppressed），这样「当时为什么没发」以后查得到"""
        self.advice_engine.save(
            computed, status=AdviceStatus.SUPPRESSED.value, suppressed_reason=reason
        )
        self._note_suppressed("推送", reason, detail)

    def _should_advise(self) -> bool:
        return self._advice_timer.is_due(now())

    # ==================== 买入后 T+n 复盘 ====================

    def _run_followups(self, prices_data: dict, decision: GateDecision) -> None:
        """为到点的买入生成复盘建议（T+1 / T+7 / T+30）。

        这是产品原始需求里「购买**后**」那一半：买完不是结束，而是要在关键时点
        主动告诉用户这笔买得怎么样、现在该怎么办。
        """
        at = now()
        if not self._followup_timer.is_due(at):
            return
        self._followup_timer.mark(at)

        # 休市静默期不生成：复盘的内容依赖当前价格，闭市时价格是冻结的，
        # 生成出来也只能说「观望」。留到开市后再做。
        if not decision.allowed:
            self._note_suppressed("买入复盘", decision.reason, decision.detail)
            return

        try:
            pending = self.advice_engine.pending_reviews(at)
        except Exception as exc:
            self.logger.error(f"查询待复盘买入失败：{exc}", exc_info=exc)
            return

        if not pending:
            return

        self.logger.info(f"发现 {len(pending)} 条待复盘买入，本次处理前 {MAX_FOLLOWUPS_PER_TICK} 条")
        for lot, horizon in pending[:MAX_FOLLOWUPS_PER_TICK]:
            self._dispatch_followup(lot, horizon, prices_data, decision)

    def _dispatch_followup(
        self,
        lot: dict,
        horizon: int,
        prices_data: dict,
        decision: GateDecision,
    ) -> None:
        symbol = str(lot.get("symbol"))
        price = self._price_for(symbol, prices_data)
        if price is None:
            self.logger.warning(f"品种 {symbol} 没有可用价格，跳过 T+{horizon} 复盘")
            return

        london_data = prices_data.get("hf_XAU") or {}
        computed = self.advice_engine.compute(
            symbol,
            price,
            london_data.get("converted_cny_price"),
            london_data.get("price"),
            subject_lot=lot,
            review_horizon=horizon,
        )

        # 复盘是「一次性事件」，靠 has_review 保证不重复，所以这里只需要过
        # 时段与优先级两道闸门，不需要动作去重。
        urgency = ACTION_URGENCY.get(computed.draft.action.value, "low")
        send_decision = self.send_gate.review(
            decision,
            key=f"{symbol}#review#{lot.get('id')}#{horizon}",
            price=price,
            urgency=urgency,
        )
        if not send_decision.allowed:
            # 刻意不落库：落库会让 has_review 变真，这条复盘就永远丢了。
            # 不落库则下一次巡检（仍在追补窗口内）会重试。
            self.logger.info(
                f"T+{horizon} 复盘暂不推送（{send_decision.reason}）：{send_decision.detail}"
            )
            return

        record = self.advice_engine.save(computed)
        extra_info = self._build_extra_info(prices_data, computed.model_info)
        if self.notification_service.send_advice(record, price, extra_info=extra_info):
            self.alert_count += 1
            self._clear_suppressed()
            self.logger.info(
                f"已推送 T+{horizon} 复盘：{computed.draft.action.value}"
                f"（建议 {record.id}）"
            )
        else:
            self.logger.warning("复盘已生成，但没有渠道投递成功")

    def _price_for(self, symbol: str, prices_data: dict) -> float | None:
        """优先用本轮刚抓到的价格，其次回落到库中最新价"""
        data = prices_data.get(symbol) or {}
        if data.get("price"):
            return float(data["price"])
        return self.price_mapper.get_latest_price(symbol)

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

    def _should_push(
        self, computed: ComputedAdvice, current_price: float
    ) -> tuple[bool, str]:
        """只在「动作变了」或「价格明显变了」时才推送，避免刷屏。

        用数据库里的上一条已推送建议做比较（而不是内存），这样重启后不会立刻重复推。
        """
        last = self.advice_engine.last_pushed(self.main_symbol)
        if last is None:
            return True, ""
        if last.action.value != computed.draft.action.value:
            return True, ""

        threshold = self.advice_engine.price_move_trigger_pct()
        if threshold > 0 and last.price_at_advice:
            move = abs(current_price - last.price_at_advice) / last.price_at_advice * 100
            if move >= threshold:
                return True, ""
        return False, "duplicate"

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
            self.logger.debug(f"[{source}] 仍然抑制（{reason}）：{detail}")
            return
        self._last_suppressed = signature
        self.logger.info(f"[{source}] 已抑制（{reason}）：{detail}")

    def _clear_suppressed(self) -> None:
        self._last_suppressed = None

    def _build_extra_info(self, prices_data: dict, model_info: str = "") -> dict:
        extra_info: dict = {}
        london_data = prices_data.get("hf_XAU")
        if london_data:
            extra_info["london_gold_usd"] = london_data["price"]
            extra_info["london_gold_cny"] = london_data.get("converted_cny_price", 0)
        if model_info:
            extra_info["ai_model_info"] = model_info
        return extra_info

    def _log_statistics(self) -> None:
        if self.check_count % 100 != 0:
            return
        run_time = (now() - self.start_time).total_seconds() / 60
        self.logger.info("=== 运行统计 ===")
        self.logger.info(f"运行时长：{run_time:.2f} 分钟")
        self.logger.info(f"检查次数：{self.check_count}")
        self.logger.info(f"报警次数：{self.alert_count}")
        self.logger.info(f"日志大小：{get_log_size() / 1024:.2f} KB")
        self.logger.info("================")

    def _cleanup_logs(self) -> None:
        at = now()
        if not self._cleanup_timer.is_due(at):
            return
        self._cleanup_timer.mark(at)
        log_config = self.settings.get_log_config()
        keep_days = log_config.get("keep_days", 30) if log_config else 30
        cleanup_old_logs(keep_days)
