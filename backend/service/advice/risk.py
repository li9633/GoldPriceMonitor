"""风险偏好 → 具体阈值与买入比例。

把「保守 / 均衡 / 进取」翻译成数字，所有倍率集中在这张表里：

| | 止盈 | 浮亏提醒 | 止损 | 单次买入 | 减持力度 | 止盈卖出 |
|---|---|---|---|---|---|---|
| 保守 | +5% | -2% | -6% | 0.6× | 1.2× | 1.2× |
| 均衡 | +8% | -3% | -10% | 1.0× | 1.0× | 1.0× |
| 进取 | +12% | -5% | -15% | 1.4× | 0.8× | 0.8× |

保守档止损更早、减得更多。
"""

from dataclasses import dataclass

#: 均衡档的基准阈值 —— 其余档位由它缩放得出，改基准等于整体平移
BASE_PROFIT_PCT = 8.0
BASE_LOSS_PCT = -3.0
BASE_DEEP_LOSS_PCT = -10.0
#: 仓位偏重的默认判定线（用户没设目标持仓占比时使用）
BASE_POSITION_RATIO_LIMIT_PCT = 100.0


@dataclass(frozen=True)
class RiskProfile:
    key: str
    label: str
    #: 浮盈超过该比例 → 考虑分批止盈
    profit_pct: float
    #: 浮亏超过该比例 → 考虑补仓
    loss_pct: float
    #: 浮亏超过该比例且趋势走坏 → 考虑减仓止损
    deep_loss_pct: float
    #: 单次买入比例的缩放系数（<1 买得更少、更慢）
    buy_fraction_scale: float
    #: 止损时的减持比例缩放（>1 减得更多）
    stop_sell_scale: float
    #: 止盈时的卖出比例缩放
    profit_sell_scale: float

    def buy_fraction(self, fraction: float) -> float:
        """把「剩余额度的几分之几」按风险偏好缩放，并封顶在 1（不能超出剩余额度）"""
        return max(min(fraction * self.buy_fraction_scale, 1.0), 0.0)

    def sell_fraction(self, fraction: float, *, take_profit: bool) -> float:
        """把「持仓的几分之几」按风险偏好缩放，并封顶在 1（不能卖出超过持有量）"""
        scale = self.profit_sell_scale if take_profit else self.stop_sell_scale
        return max(min(fraction * scale, 1.0), 0.0)


PROFILES: dict[str, RiskProfile] = {
    "conservative": RiskProfile(
        key="conservative",
        label="保守",
        profit_pct=5.0,
        loss_pct=-2.0,
        deep_loss_pct=-6.0,
        buy_fraction_scale=0.6,
        stop_sell_scale=1.2,
        profit_sell_scale=1.2,
    ),
    "balanced": RiskProfile(
        key="balanced",
        label="均衡",
        profit_pct=BASE_PROFIT_PCT,
        loss_pct=BASE_LOSS_PCT,
        deep_loss_pct=BASE_DEEP_LOSS_PCT,
        buy_fraction_scale=1.0,
        stop_sell_scale=1.0,
        profit_sell_scale=1.0,
    ),
    "aggressive": RiskProfile(
        key="aggressive",
        label="进取",
        profit_pct=12.0,
        loss_pct=-5.0,
        deep_loss_pct=-15.0,
        buy_fraction_scale=1.4,
        stop_sell_scale=0.8,
        profit_sell_scale=0.8,
    ),
}

DEFAULT_RISK_KEY = "balanced"


def resolve_risk(key: str | None) -> RiskProfile:
    """未知档位一律回落到均衡，不抛异常 —— 配置脏数据不该让建议生成失败"""
    return PROFILES.get(str(key or "").strip().lower(), PROFILES[DEFAULT_RISK_KEY])


def position_ratio_limit(prefs) -> float:
    """仓位偏重的判定线：用户设了目标持仓占比就用它，否则用经验默认值"""
    if prefs.target_position_ratio > 0:
        return float(prefs.target_position_ratio)
    return BASE_POSITION_RATIO_LIMIT_PCT
