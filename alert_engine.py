# alert_engine.py
from typing import List
from history_manager import HistoryManager
from config import AlertConfig


class AlertEngine:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.history_manager = HistoryManager()
        self.config = AlertConfig

    def check_all_conditions(self, current_price: float) -> List[str]:
        """检查所有启用的报警条件，返回报警信息列表"""
        alerts = []

        # 条件1: 绝对阈值
        if self._check_absolute_low(current_price):
            alerts.append(self._format_absolute_alert(current_price))

        # 条件2: 相对低点
        if self._check_relative_low(current_price):
            alerts.append(self._format_relative_alert(current_price))

        # 条件3: 窄幅震荡突破
        if self._check_breakout(current_price):
            alerts.append(self._format_breakout_alert(current_price))

        return alerts

    def _check_absolute_low(self, current_price: float) -> bool:
        """检查绝对低价阈值"""
        if not self.config.ENABLE_ABSOLUTE_ALERT:
            return False
        return current_price < self.config.ABSOLUTE_LOW_PRICE

    def _check_relative_low(self, current_price: float) -> bool:
        """检查是否为近期低点"""
        if not self.config.ENABLE_RELATIVE_ALERT:
            return False

        window_hours = self.config.RELATIVE_WINDOW_HOURS
        recent_prices = self.history_manager.get_prices_in_window(
            self.symbol, window_hours)

        if not recent_prices:
            return False

        return current_price <= min(recent_prices)

    def _check_breakout(self, current_price: float) -> bool:
        """检查窄幅震荡突破"""
        if not self.config.ENABLE_BREAKOUT_ALERT:
            return False

        hours = self.config.CONSOLIDATION_HOURS
        prices = self.history_manager.get_prices_in_window(self.symbol, hours)

        if len(prices) < 10:  # 数据点不足
            return False

        high = max(prices)
        low = min(prices)
        volatility = (high - low) / low

        is_consolidation = volatility < self.config.VOLATILITY_THRESHOLD
        is_breakout = current_price < low

        return is_consolidation and is_breakout

    def _format_absolute_alert(self, price: float) -> str:
        return f"⚠️ 绝对低价报警！当前价格 {price} 低于设定阈值 {self.config.ABSOLUTE_LOW_PRICE}"

    def _format_relative_alert(self, price: float) -> str:
        window = self.config.RELATIVE_WINDOW_HOURS
        return f"📉 近期低点报警！当前价格 {price} 是过去{window}小时内的最低点。"

    def _format_breakout_alert(self, price: float) -> str:
        hours = self.config.CONSOLIDATION_HOURS
        prices = self.history_manager.get_prices_in_window(self.symbol, hours)
        low = min(prices)
        high = max(prices)
        volatility = (high - low) / low
        return f"🔻 突破盘整报警！在{hours}小时内窄幅震荡({volatility:.2%})，当前价{price}已突破下轨{low}"
