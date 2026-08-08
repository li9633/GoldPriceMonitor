from mapper.price_mapper import PriceMapper, PriceSnapshot
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("AlertService")


class AlertService:
    def __init__(self, symbol: str, price_mapper: PriceMapper | None = None):
        self.symbol = symbol
        self.price_mapper = price_mapper if price_mapper else PriceMapper()
        self.settings = SystemSettingsService()
        self.config = self.settings.get_alert_config()
        self.price_history = []
        self.alert_records: dict[str, dict] = {}
        self.alert_cooldown_minutes = 10
        self.price_change_threshold = 0.003

    def refresh_config(self, symbol: str | None = None) -> None:
        if symbol is not None:
            self.symbol = symbol
        self.config = self.settings.get_alert_config()
        logger.info(f"AlertService 配置已刷新，symbol={self.symbol}")

    def check_all_conditions(self, current_price: float) -> tuple[list[str], list[str]]:
        alerts = []
        suggestions = []

        snapshot = self.price_mapper.get_check_snapshot(self.symbol)

        # 绝对价格预警（底线安全，始终启用）
        result = self._check_absolute_low(current_price, snapshot)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 以下算法检查已由 AI 分析替代，代码保留以便后续恢复
        # checks = [
        #     self._check_relative_low,
        #     self._check_breakout,
        #     self._check_trend_reversal,
        #     self._check_volatility_anomaly,
        #     self._check_ma_cross,
        #     self._check_consecutive_move,
        #     self._check_rapid_price_change,
        #     self._check_long_term_low,
        # ]
        # for check in checks:
        #     result = check(current_price, snapshot)
        #     if result[0]:
        #         alerts.append(result[0])
        #         suggestions.append(result[1])

        self.price_history.append(current_price)
        if len(self.price_history) > 100:
            self.price_history.pop(0)

        return alerts, suggestions

    def _should_send_alert(self, alert_type: str, current_price: float) -> bool:
        now_dt = now()
        if alert_type not in self.alert_records:
            self.alert_records[alert_type] = {
                "last_time": now_dt,
                "last_price": current_price,
            }
            return True

        record = self.alert_records[alert_type]
        time_diff = (now_dt - record["last_time"]).total_seconds() / 60
        if time_diff < self.alert_cooldown_minutes:
            price_change = (
                abs(current_price - record["last_price"]) / record["last_price"]
                if record["last_price"] > 0
                else 0
            )
            if price_change < self.price_change_threshold:
                logger.debug(f"报警去重跳过：{alert_type}")
                return False

        record["last_time"] = now_dt
        record["last_price"] = current_price
        return True

    def _check_absolute_low(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_absolute_alert"]:
            return None, None
        if current_price < self.config["absolute_low_price"]:
            alert = f"绝对低价报警！当前价格 {current_price} 低于设定阈值 {self.config['absolute_low_price']}"
            suggestion = "建议：可能是买入机会，请结合基本面分析后决策"
            return alert, suggestion
        return None, None

    def _check_relative_low(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_relative_alert"] or snapshot is None:
            return None, None
        window_hours = self.config["relative_window_hours"]
        threshold = snapshot.percentile(window_hours, 10)
        if threshold and current_price <= threshold:
            if not self._should_send_alert("relative_low", current_price):
                return None, None
            alert = f"近期低点报警！当前价格处于过去{window_hours}小时内的 10% 分位以下"
            suggestion = f"建议：价格处于低位区域，可关注是否反弹，设置止损位 {threshold * 0.98:.2f}"
            return alert, suggestion
        return None, None

    def _check_breakout(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_breakout_alert"] or snapshot is None:
            return None, None
        hours = self.config["consolidation_hours"]
        prices = snapshot.prices_in_hours(hours)
        if len(prices) < 10:
            return None, None
        high = max(prices)
        low = min(prices)
        avg = sum(prices) / len(prices)
        volatility = (high - low) / avg if avg > 0 else 0
        is_consolidation = volatility < self.config["volatility_threshold"]
        is_breakout = current_price < low * 0.995
        if is_consolidation and is_breakout:
            if not self._should_send_alert("breakout", current_price):
                return None, None
            alert = f"突破盘整报警！{hours} 小时窄幅震荡后突破下轨 {low}"
            suggestion = "建议：突破可能引发加速下跌，谨慎观望或设置止损"
            return alert, suggestion
        return None, None

    def _check_trend_reversal(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if snapshot is None:
            return None, None
        trend_6h = snapshot.trend(6)
        trend_24h = snapshot.trend(24)
        if not trend_6h or not trend_24h:
            return None, None
        if trend_6h["direction"] == "down" and trend_24h["direction"] == "up":
            ma_24 = snapshot.ma(48)
            if ma_24 and current_price < ma_24 * 0.98:
                if not self._should_send_alert("trend_reversal", current_price):
                    return None, None
                alert = "趋势反转预警！短期下跌与长期上涨趋势背离"
                suggestion = (
                    f"建议：趋势可能反转，关注 {ma_24:.2f} 均线支撑，破位则减仓"
                )
                return alert, suggestion
        return None, None

    def _check_volatility_anomaly(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if snapshot is None:
            return None, None
        stats = snapshot.statistics(24)
        if not stats or "std" not in stats or stats["count"] < 10:
            return None, None
        deviation = abs(current_price - stats["avg"])
        if deviation > 2 * stats["std"]:
            if not self._should_send_alert("volatility_anomaly", current_price):
                return None, None
            alert = (
                f"波动率异常！价格偏离 24 小时均值 ({stats['avg']:.2f}) 超过 2 倍标准差"
            )
            suggestion = "建议：市场波动加剧，注意风险控制，避免追涨杀跌"
            return alert, suggestion
        return None, None

    def _check_ma_cross(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_ma_cross_alert"] or snapshot is None:
            return None, None
        ma_short = snapshot.ma(self.config["ma_short_period"])
        ma_long = snapshot.ma(self.config["ma_long_period"])
        if not ma_short or not ma_long:
            return None, None
        prev_prices = snapshot.prices_last_n(self.config["ma_short_period"] + 1)
        if len(prev_prices) < self.config["ma_short_period"] + 1:
            return None, None
        prev_ma_short = (
            sum(prev_prices[: self.config["ma_short_period"]])
            / self.config["ma_short_period"]
        )
        prev_ma_long = ma_long
        if prev_ma_short <= prev_ma_long and ma_short > ma_long:
            if not self._should_send_alert("ma_golden_cross", current_price):
                return None, None
            alert = f"金叉信号！{self.config['ma_short_period']} 周期均线上穿 {self.config['ma_long_period']} 周期均线"
            suggestion = "建议：看涨信号，可考虑分批建仓，止损位设在近期低点"
            return alert, suggestion
        if prev_ma_short >= prev_ma_long and ma_short < ma_long:
            if not self._should_send_alert("ma_death_cross", current_price):
                return None, None
            alert = f"死叉信号！{self.config['ma_short_period']} 周期均线下穿 {self.config['ma_long_period']} 周期均线"
            suggestion = "建议：看跌信号，注意减仓或设置止损，关注支撑位"
            return alert, suggestion
        return None, None

    def _check_consecutive_move(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_consecutive_alert"] or snapshot is None:
            return None, None
        count = self.config["consecutive_count"]
        recent_prices = snapshot.prices_in_hours(2)
        if len(recent_prices) < count + 1:
            return None, None
        directions = []
        for i in range(len(recent_prices) - count, len(recent_prices)):
            if recent_prices[i] > recent_prices[i - 1]:
                directions.append("up")
            elif recent_prices[i] < recent_prices[i - 1]:
                directions.append("down")
            else:
                directions.append("stable")
        if all(d == "up" for d in directions[-count:]):
            if not self._should_send_alert("consecutive_up", current_price):
                return None, None
            change_pct = (
                (recent_prices[-1] - recent_prices[-count - 1])
                / recent_prices[-count - 1]
                * 100
            )
            alert = f"连续上涨报警！已持续{count} 周期上涨，累计涨幅{change_pct:.2f}%"
            suggestion = "建议：警惕回调风险，不宜追高，可考虑部分止盈"
            return alert, suggestion
        if all(d == "down" for d in directions[-count:]):
            if not self._should_send_alert("consecutive_down", current_price):
                return None, None
            change_pct = (
                (recent_prices[-count - 1] - recent_prices[-1])
                / recent_prices[-count - 1]
                * 100
            )
            alert = f"连续下跌报警！已持续{count} 周期下跌，累计跌幅{change_pct:.2f}%"
            suggestion = "建议：关注反弹机会，可分批建仓，设置止损位"
            return alert, suggestion
        return None, None

    def _check_rapid_price_change(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_rapid_change_alert"] or snapshot is None:
            return None, None
        window_hours = self.config["rapid_change_window_minutes"] / 60
        recent_prices = snapshot.prices_in_hours(window_hours)
        if len(recent_prices) < 2:
            return None, None
        start_price = recent_prices[0]
        if start_price <= 0:
            return None, None
        change_pct = abs(current_price - start_price) / start_price
        if change_pct >= self.config["rapid_change_threshold"]:
            if not self._should_send_alert("rapid_change", current_price):
                return None, None
            direction = "上涨" if current_price > start_price else "下跌"
            alert = f"快速{direction}报警！{self.config['rapid_change_window_minutes']} 分钟内价格{direction}{change_pct * 100:.2f}%"
            if current_price > start_price:
                suggestion = "建议：快速上涨可能伴随回调，避免追高，等待企稳"
            else:
                suggestion = "建议：快速下跌可能超卖，关注支撑位，可考虑分批买入"
            return alert, suggestion
        return None, None

    def _check_long_term_low(
        self, current_price: float, snapshot: PriceSnapshot | None
    ) -> tuple[str | None, str | None]:
        if not self.config["enable_long_term_low_alert"] or snapshot is None:
            return None, None
        if snapshot.min_3m is not None and current_price <= snapshot.min_3m * 1.005:
            if not self._should_send_alert("long_term_low_3m", current_price):
                return None, None
            alert = f"3 个月最低价报警！当前价格 {current_price} 接近 3 个月低点 {snapshot.min_3m:.2f}"
            suggestion = f"建议：价格处于 3 个月低位，可关注长期支撑，设置止损位 {snapshot.min_3m * 0.97:.2f}"
            return alert, suggestion
        if snapshot.min_6m is not None and current_price <= snapshot.min_6m * 1.005:
            if not self._should_send_alert("long_term_low_6m", current_price):
                return None, None
            alert = f"6 个月最低价报警！当前价格 {current_price} 接近 6 个月低点 {snapshot.min_6m:.2f}"
            suggestion = "建议：价格处于 6 个月低位，重要长期支撑位，可考虑分批建仓"
            return alert, suggestion
        return None, None
