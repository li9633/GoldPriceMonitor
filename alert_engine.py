from typing import List, Tuple, Optional, Dict
from history_manager import HistoryManager
from config import AlertConfig
from datetime import datetime


class AlertEngine:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.history_manager = HistoryManager()
        self.config = AlertConfig
        self.price_history = []
        # 报警记录，记录每种报警类型的最后触发时间和价格
        self.alert_records: Dict[str, Dict] = {}
        # 报警冷却时间（分钟）
        self.alert_cooldown_minutes = 30
        # 价格变化阈值（百分比）
        self.price_change_threshold = 0.005  # 0.5%

    def check_all_conditions(self, current_price: float) -> Tuple[List[str], List[str]]:
        """检查所有报警条件

        Returns:
            (alerts, suggestions) 报警信息列表和操作建议列表
        """
        alerts = []
        suggestions = []

        # 条件 1: 绝对阈值
        result = self._check_absolute_low(current_price)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 条件 2: 相对低点
        result = self._check_relative_low(current_price)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 条件 3: 窄幅震荡突破
        result = self._check_breakout(current_price)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 条件 4: 趋势反转预警
        result = self._check_trend_reversal(current_price)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 条件 5: 波动率异常
        result = self._check_volatility_anomaly(current_price)
        if result[0]:
            alerts.append(result[0])
            suggestions.append(result[1])

        # 缓存价格
        self.price_history.append(current_price)
        if len(self.price_history) > 100:
            self.price_history.pop(0)

        return alerts, suggestions

    def _should_send_alert(self, alert_type: str, current_price: float) -> bool:
        """判断是否应该发送报警（去重逻辑）
        
        Args:
            alert_type: 报警类型标识
            current_price: 当前价格
            
        Returns:
            bool: True 表示可以发送，False 表示跳过
        """
        now = datetime.now()

        if alert_type not in self.alert_records:
            # 首次报警，允许发送
            self.alert_records[alert_type] = {
                'last_time': now,
                'last_price': current_price
            }
            return True

        record = self.alert_records[alert_type]
        last_time = record['last_time']
        last_price = record['last_price']

        # 检查冷却时间
        time_diff = (now - last_time).total_seconds() / 60
        if time_diff < self.alert_cooldown_minutes:
            # 在冷却期内，检查价格是否有显著变化
            price_change = abs(current_price - last_price) / \
                last_price if last_price > 0 else 0
            if price_change < self.price_change_threshold:
                # 价格变化不大，跳过报警
                return False

        # 更新记录
        record['last_time'] = now
        record['last_price'] = current_price
        return True

    def _check_absolute_low(self, current_price: float) -> Tuple[Optional[str], Optional[str]]:
        """检查绝对低价阈值"""
        if not self.config.ENABLE_ABSOLUTE_ALERT:
            return None, None
        if current_price < self.config.ABSOLUTE_LOW_PRICE:
            # 去重判断
            if not self._should_send_alert('absolute_low', current_price):
                return None, None

            alert = f"绝对低价报警！当前价格 {current_price} 低于设定阈值 {self.config.ABSOLUTE_LOW_PRICE}"
            suggestion = "建议：可能是买入机会，请结合基本面分析后决策"
            return alert, suggestion
        return None, None

    def _check_relative_low(self, current_price: float) -> Tuple[Optional[str], Optional[str]]:
        """检查是否为近期低点"""
        if not self.config.ENABLE_RELATIVE_ALERT:
            return None, None

        window_hours = self.config.RELATIVE_WINDOW_HOURS
        recent_prices = self.history_manager.get_prices_in_window(
            self.symbol, window_hours)

        if not recent_prices:
            return None, None

        threshold = self.history_manager.get_percentile(
            self.symbol, window_hours, 10)

        if threshold and current_price <= threshold:
            # 去重判断
            if not self._should_send_alert('relative_low', current_price):
                return None, None

            alert = f"近期低点报警！当前价格处于过去{window_hours}小时内的 10% 分位以下"
            suggestion = f"建议：价格处于低位区域，可关注是否反弹，设置止损位 {threshold * 0.98:.2f}"
            return alert, suggestion
        return None, None

    def _check_breakout(self, current_price: float) -> Tuple[Optional[str], Optional[str]]:
        """检查窄幅震荡突破"""
        if not self.config.ENABLE_BREAKOUT_ALERT:
            return None, None

        hours = self.config.CONSOLIDATION_HOURS
        prices = self.history_manager.get_prices_in_window(self.symbol, hours)

        if len(prices) < 10:
            return None, None

        high = max(prices)
        low = min(prices)
        avg = sum(prices) / len(prices)
        volatility = (high - low) / avg if avg > 0 else 0

        is_consolidation = volatility < self.config.VOLATILITY_THRESHOLD
        is_breakout = current_price < low * 0.995

        if is_consolidation and is_breakout:
            # 去重判断
            if not self._should_send_alert('breakout', current_price):
                return None, None

            alert = f"突破盘整报警！{hours} 小时窄幅震荡后突破下轨 {low}"
            suggestion = "建议：突破可能引发加速下跌，谨慎观望或设置止损"
            return alert, suggestion
        return None, None

    def _check_trend_reversal(self, current_price: float) -> Tuple[Optional[str], Optional[str]]:
        """检查趋势反转"""
        trend_6h = self.history_manager.get_price_trend(self.symbol, 6)
        trend_24h = self.history_manager.get_price_trend(self.symbol, 24)

        if not trend_6h or not trend_24h:
            return None, None

        if trend_6h['direction'] == 'down' and trend_24h['direction'] == 'up':
            ma_24 = self.history_manager.get_moving_average(self.symbol, 48)
            if ma_24 and current_price < ma_24 * 0.98:
                # 去重判断
                if not self._should_send_alert('trend_reversal', current_price):
                    return None, None

                alert = "趋势反转预警！短期下跌与长期上涨趋势背离"
                suggestion = f"建议：趋势可能反转，关注 {ma_24:.2f} 均线支撑，破位则减仓"
                return alert, suggestion
        return None, None

    def _check_volatility_anomaly(self, current_price: float) -> Tuple[Optional[str], Optional[str]]:
        """检查波动率异常"""
        stats = self.history_manager.get_price_statistics(self.symbol, 24)

        if not stats or 'std' not in stats or stats['count'] < 10:
            return None, None

        deviation = abs(current_price - stats['avg'])
        if deviation > 2 * stats['std']:
            # 去重判断
            if not self._should_send_alert('volatility_anomaly', current_price):
                return None, None

            alert = f"波动率异常！价格偏离 24 小时均值 ({stats['avg']:.2f}) 超过 2 倍标准差"
            suggestion = "建议：市场波动加剧，注意风险控制，避免追涨杀跌"
            return alert, suggestion
        return None, None
