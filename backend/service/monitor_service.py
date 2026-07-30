import time
from datetime import datetime

from config import CHINA_TZ
from mapper.price_mapper import PriceMapper
from service.ai_service import AIAnalysisService
from service.alert_service import AlertService
from service.history_import_service import init_historical_data
from service.notification_service import NotificationService
from service.price_service import PriceService
from service.system_settings_service import SystemSettingsService
from utils.logger import cleanup_old_logs, get_log_size, get_logger


class MonitorService:
    def __init__(self):
        self.logger = get_logger("GoldPriceMonitor")
        self.settings = SystemSettingsService()
        self.price_mapper = PriceMapper()
        self.price_service = PriceService()
        self.notification_service = NotificationService()
        self.ai_service = AIAnalysisService()
        self.start_time = datetime.now(CHINA_TZ)
        self.check_count = 0
        self.alert_count = 0
        self._last_ai_check_time: datetime | None = None
        self._last_settings_refresh = datetime.now(CHINA_TZ)
        self._last_notification_time: datetime | None = None
        self._notification_cooldown_minutes = 5

        self._refresh_settings()
        self.alert_service = AlertService(self.main_symbol, self.price_mapper)

    def _refresh_settings(self) -> None:
        monitor_config = self.settings.get_monitor_config()
        self.main_symbol = monitor_config.get("main_symbol", "gds_AUTD")
        self.monitor_symbols = monitor_config.get(
            "monitor_symbols", ["gds_AUTD", "hf_XAU"]
        )
        self.check_interval = monitor_config.get("check_interval", 10)

        ai_config = self.settings.get_ai_config()
        self.ai_check_interval_minutes = ai_config.get("check_interval_minutes", 5)

        if hasattr(self, "alert_service"):
            self.alert_service.refresh_config(self.main_symbol)

        self._last_settings_refresh = datetime.now(CHINA_TZ)

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
                f"[{datetime.now(CHINA_TZ)}] 获取主品种 {self.main_symbol} 价格失败，等待下次检查"
            )
            self.check_count += 1
            return

        current_price = main_symbol_data["price"]
        self.logger.debug(
            f"[{datetime.now(CHINA_TZ).strftime('%H:%M:%S')}] {main_symbol_data['name']} 价格：{current_price}"
        )

        self._save_prices(prices_data, current_price)
        self._handle_alerts(prices_data, current_price)
        self._periodic_ai_check(prices_data, current_price)
        self._log_statistics()
        self._cleanup_logs()

        self.check_count += 1

    def _save_prices(self, prices_data: dict, current_price: float) -> None:
        self.price_mapper.save_price(self.main_symbol, current_price)
        london_data = prices_data.get("hf_XAU")
        if london_data:
            self.price_mapper.save_price("hf_XAU", london_data["price"])

    def _handle_alerts(self, prices_data: dict, current_price: float) -> None:
        alerts, suggestions = self.alert_service.check_all_conditions(current_price)

        extra_info = self._build_extra_info(prices_data)

        if not alerts:
            self.logger.debug("  └─ 无报警")
            return

        self.alert_count += 1
        self.logger.warning(f"触发 {len(alerts)} 条报警")
        for alert in alerts:
            self.logger.warning(f"  └─ {alert}")

        should_send = True
        ai_result = self._call_ai(prices_data, current_price, alerts)
        if ai_result is not None:
            if ai_result.get("should_alert"):
                alerts[:] = [ai_result.get("analysis", "")]
                suggestions[:] = ai_result.get("suggestions", [])
                extra_info["ai_model_info"] = (
                    f"{ai_result.get('provider', '')}/{ai_result.get('model', '')}"
                )
                self.logger.info(f"AI 确认发送通知（{ai_result.get('urgency', '')}）")
            else:
                should_send = False
                self.logger.info("AI 判断无需发送通知，已跳过")
        else:
            self.logger.warning("AI 分析不可用，回退到原始报警逻辑")

        if should_send:
            self.notification_service.send_alert(
                self.main_symbol,
                current_price,
                alerts,
                suggestions,
                extra_info=extra_info,
            )

    def _periodic_ai_check(self, prices_data: dict, current_price: float) -> None:
        if not self._should_ai_check():
            return

        self.logger.info("正在调用 AI 分析行情...")
        ai_result = self._call_ai(prices_data, current_price)
        self._last_ai_check_time = datetime.now(CHINA_TZ)

        if not ai_result or not ai_result.get("should_alert"):
            return

        self.alert_count += 1
        urgency = ai_result.get("urgency", "unknown")
        analysis_preview = ai_result.get("analysis", "")[:50]
        self.logger.warning(f"AI 建议通知（{urgency}）：{analysis_preview}...")

        ai_alerts = [ai_result.get("analysis", "")]
        ai_suggestions = ai_result.get("suggestions", [])
        extra_info = self._build_extra_info(prices_data)
        extra_info["ai_model_info"] = (
            f"{ai_result.get('provider', '')}/{ai_result.get('model', '')}"
        )

        self.notification_service.send_alert(
            self.main_symbol,
            current_price,
            ai_alerts,
            ai_suggestions,
            extra_info=extra_info,
        )
        self._last_notification_time = datetime.now(CHINA_TZ)

    def _should_ai_check(self) -> bool:
        if self._last_ai_check_time is None:
            return True
        elapsed = (datetime.now(CHINA_TZ) - self._last_ai_check_time).total_seconds()
        return elapsed >= self.ai_check_interval_minutes * 60

    def _refresh_settings_if_needed(self) -> None:
        elapsed = (datetime.now(CHINA_TZ) - self._last_settings_refresh).total_seconds()
        if elapsed >= 60:
            self._refresh_settings()

    def _is_in_cooldown(self) -> bool:
        if self._last_notification_time is None:
            return False
        elapsed = (
            datetime.now(CHINA_TZ) - self._last_notification_time
        ).total_seconds() / 60
        return elapsed < self._notification_cooldown_minutes

    def _call_ai(
        self,
        prices_data: dict,
        current_price: float,
        triggered_alerts: list[str] | None = None,
    ) -> dict | None:
        london_data = prices_data.get("hf_XAU")
        london_cny = london_data.get("converted_cny_price") if london_data else None
        london_usd = london_data["price"] if london_data else None
        snapshot = self.price_mapper.get_check_snapshot(self.main_symbol)
        return self.ai_service.analyze(
            self.main_symbol,
            current_price,
            snapshot,
            london_cny,
            london_usd,
            triggered_alerts,
        )

    def _build_extra_info(self, prices_data: dict) -> dict:
        extra_info = {}
        london_data = prices_data.get("hf_XAU")
        if london_data:
            extra_info["london_gold_usd"] = london_data["price"]
            extra_info["london_gold_cny"] = london_data.get("converted_cny_price", 0)
        return extra_info

    def _log_statistics(self) -> None:
        if self.check_count % 100 != 0:
            return
        run_time = (datetime.now(CHINA_TZ) - self.start_time).total_seconds() / 60
        self.logger.info("=== 运行统计 ===")
        self.logger.info(f"运行时长：{run_time:.2f} 分钟")
        self.logger.info(f"检查次数：{self.check_count}")
        self.logger.info(f"报警次数：{self.alert_count}")
        self.logger.info(f"日志大小：{get_log_size() / 1024:.2f} KB")
        self.logger.info("================")

    def _cleanup_logs(self) -> None:
        if self.check_count % (86400 // self.check_interval) == 0:
            log_config = self.settings.get_log_config()
            keep_days = log_config.get("keep_days", 30) if log_config else 30
            cleanup_old_logs(keep_days)
