"""建仓方式评估 —— 用真实历史回测「一次性 vs 分批」。

这是把「分批还是一次性」从经验规则变成**有证据**的建议：给定当前市场状态，
在过去一年的历史里找出相似环境，比较两种做法持有到期末的平均成本。

- `lump_sum`：第 0 天一次买满
- `interval(N)`：分成 N 批，按固定时间间隔买入
- `drop_pct(N)`：分成 N 批，按「较上一批跌 `DROP_TRIGGER_PCT`%」触发补仓；
  到期末仍未触发的部分按期末价补足，否则与一次性不可比

所有计算都是**纯函数**（输入是价格序列），`fetch_series()` 才碰数据库，
所以核心逻辑可以脱离数据库单测。

**诚实优先**：样本不足时明确返回 `insufficient_data=True` 并建议一次性，
而不是用几个样本编出一个结论。
"""

import math
import time
from dataclasses import dataclass, field
from datetime import date

from utils.logger import get_logger

logger = get_logger("EntryStrategy")

#: 计算波动率用的滚动窗口（天）
VOL_WINDOW_DAYS = 20
#: 默认回看天数与评估持有期（天）
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_HORIZON_DAYS = 30
#: 候选批次数
TRANCHES_CANDIDATES = (2, 3, 4, 5)
#: 「跌 x% 补一批」的触发阈值
DROP_TRIGGER_PCT = 1.0
#: 少于该样本数就不给结论
MIN_SAMPLES = 20
#: 「最坏情况」容忍度：随「一次性买入价本身的离散度」自适应，并设上下限。
#: 含义是——分批最坏比一次性贵多少，才算还在可接受范围内。
#: 一次性买入价本身波动越大，分批多付一点就越无所谓。
SPLIT_WORST_CASE_FLOOR_PCT = 1.5
SPLIT_WORST_CASE_CAP_PCT = 6.0
#: 波动率相似度区间，逐级放宽直到样本足够
_VOL_BANDS = ((0.4, 1.6), (0.25, 2.5), (0.0, math.inf))


@dataclass(frozen=True)
class StrategyOutcome:
    """一种建仓方式在历史相似环境下的表现"""

    method: str  # lump_sum / interval / drop_pct
    tranches: int
    avg_cost_diff_pct: float  # 相对一次性的平均成本差异（负 = 更便宜）
    worst_case_pct: float  # 最坏情况下比一次性贵多少
    best_case_pct: float  # 最好情况下比一次性便宜多少
    win_rate_pct: float  # 跑赢一次性的样本占比
    sample_count: int

    @property
    def label(self) -> str:
        if self.method == "lump_sum":
            return "一次性买入"
        if self.method == "interval":
            return f"分 {self.tranches} 批（按时间）"
        return f"分 {self.tranches} 批（按跌幅 {DROP_TRIGGER_PCT:g}%）"


@dataclass
class EntryStrategyResult:
    """建仓方式评估结论"""

    symbol: str
    current_price: float
    lookback_days: int
    horizon_days: int
    series_points: int
    volatility_pct: float | None
    volatility_percentile: float | None
    sample_count: int
    vol_band: tuple[float, float] | None
    outcomes: list[StrategyOutcome] = field(default_factory=list)
    recommended: StrategyOutcome | None = None
    recommended_tranches: int = 1
    sufficient_data: bool = False
    explanation: str = ""
    #: 各样本「一次性买入价」的离散度（%）；最坏情况容忍度由它决定
    lump_dispersion_pct: float | None = None
    worst_case_tolerance_pct: float | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "lookback_days": self.lookback_days,
            "horizon_days": self.horizon_days,
            "series_points": self.series_points,
            "volatility_pct": self.volatility_pct,
            "volatility_percentile": self.volatility_percentile,
            "sample_count": self.sample_count,
            "vol_band": list(self.vol_band) if self.vol_band else None,
            "recommended_tranches": self.recommended_tranches,
            "sufficient_data": self.sufficient_data,
            "explanation": self.explanation,
            "lump_dispersion_pct": self.lump_dispersion_pct,
            "worst_case_tolerance_pct": self.worst_case_tolerance_pct,
            "recommended": self.recommended.__dict__ if self.recommended else None,
            "outcomes": [outcome.__dict__ for outcome in self.outcomes],
        }


# ==================== 纯计算 ====================


def rolling_volatility(prices: list[float], window: int = VOL_WINDOW_DAYS) -> list[float]:
    """滚动波动率（收益率的标准差，%）。前 `window` 个位置填 0。"""
    vols = [0.0] * len(prices)
    if len(prices) <= window:
        return vols
    returns = [0.0] * len(prices)
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        returns[i] = (prices[i] - prev) / prev if prev > 0 else 0.0

    for i in range(window, len(prices)):
        chunk = returns[i - window + 1 : i + 1]
        mean = sum(chunk) / len(chunk)
        variance = sum((value - mean) ** 2 for value in chunk) / len(chunk)
        vols[i] = math.sqrt(variance) * 100
    return vols


def percentile_rank(values: list[float], target: float) -> float | None:
    """`target` 在 `values` 中的分位（0-100）"""
    usable = [value for value in values if value > 0]
    if not usable or target <= 0:
        return None
    below = sum(1 for value in usable if value <= target)
    return below / len(usable) * 100


def simulate_avg_cost(
    window: list[float], method: str, tranches: int, horizon: int
) -> float:
    """在 `window`（长度 = horizon + 1）上模拟一种建仓方式的每克平均成本。

    份额归一化（总克数视为 1），所以返回值可直接与 `window[0]` 比较。
    """
    if method == "lump_sum" or tranches <= 1:
        return window[0]

    if method == "interval":
        step = max(horizon // tranches, 1)
        total = 0.0
        per = 1.0 / tranches
        for i in range(tranches):
            index = min(i * step, horizon)
            total += per * window[index]
        return total

    # drop_pct：首批立即买入，其余按跌幅触发，期末补足
    per = 1.0 / tranches
    total = per * window[0]
    remaining = tranches - 1
    last_price = window[0]
    for day in range(1, horizon + 1):
        if remaining == 0:
            break
        price = window[day]
        if last_price > 0 and price <= last_price * (1 - DROP_TRIGGER_PCT / 100):
            total += per * price
            last_price = price
            remaining -= 1
    if remaining > 0:
        total += remaining * per * window[horizon]
    return total


def _collect_samples(
    prices: list[float],
    vols: list[float],
    today_vol: float,
    horizon: int,
) -> tuple[list[int], tuple[float, float] | None]:
    """挑出「波动率与当前相似」且前方有足够数据的起始位置。

    相似区间逐级放宽，直到样本数够用 —— 并把这个区间返回给调用方，
    这样结论里能诚实说明「用的是多大范围的历史」。
    """
    last_start = len(prices) - horizon - 1
    if last_start < VOL_WINDOW_DAYS:
        return [], None

    if today_vol <= 0:
        return list(range(VOL_WINDOW_DAYS, last_start + 1)), None

    for low_ratio, high_ratio in _VOL_BANDS:
        low = today_vol * low_ratio
        high = today_vol * high_ratio if math.isfinite(high_ratio) else math.inf
        starts = [
            i
            for i in range(VOL_WINDOW_DAYS, last_start + 1)
            if low <= vols[i] <= high
        ]
        if len(starts) >= MIN_SAMPLES:
            return starts, (low_ratio, high_ratio)
    return [], None


def evaluate_entry_strategy(
    symbol: str,
    series: list[tuple[date, float]],
    current_price: float,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> EntryStrategyResult:
    """在历史序列上回测各种建仓方式。

    `series` 按时间升序；`current_price` 用于给出当前波动率分位（序列最后一点
    通常就是当前价，但显式传入更清晰）。
    """
    prices = [price for _, price in series if price and price > 0]
    result = EntryStrategyResult(
        symbol=symbol,
        current_price=current_price,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        series_points=len(prices),
        volatility_pct=None,
        volatility_percentile=None,
        sample_count=0,
        vol_band=None,
    )

    needed = VOL_WINDOW_DAYS + horizon_days + MIN_SAMPLES
    if len(prices) < needed:
        result.explanation = (
            f"历史数据不足（只有 {len(prices)} 个数据点，至少需要 {needed} 个），"
            "无法回测建仓方式，建议先按一次性买入处理"
        )
        return result

    vols = rolling_volatility(prices)
    today_vol = vols[-1]
    result.volatility_pct = round(today_vol, 4)
    result.volatility_percentile = percentile_rank(vols[VOL_WINDOW_DAYS:], today_vol)
    if result.volatility_percentile is not None:
        result.volatility_percentile = round(result.volatility_percentile, 1)

    starts, band = _collect_samples(prices, vols, today_vol, horizon_days)
    result.vol_band = band
    result.sample_count = len(starts)

    if len(starts) < MIN_SAMPLES:
        result.explanation = (
            f"历史上找不到足够相似的市场环境（仅 {len(starts)} 个样本，"
            f"少于 {MIN_SAMPLES} 个），无法给出可靠结论，建议按一次性买入处理"
        )
        return result

    candidates: list[tuple[str, int]] = [("interval", n) for n in TRANCHES_CANDIDATES]
    candidates += [("drop_pct", n) for n in TRANCHES_CANDIDATES]

    diffs: dict[tuple[str, int], list[float]] = {key: [] for key in candidates}
    lump_costs: list[float] = []
    for start in starts:
        window = prices[start : start + horizon_days + 1]
        base = window[0]
        if base <= 0:
            continue
        lump_costs.append(base)
        for key in candidates:
            avg = simulate_avg_cost(window, key[0], key[1], horizon_days)
            diffs[key].append((avg - base) / base * 100)

    outcomes: list[StrategyOutcome] = []
    for key, values in diffs.items():
        if not values:
            continue
        wins = sum(1 for value in values if value < 0)
        outcomes.append(
            StrategyOutcome(
                method=key[0],
                tranches=key[1],
                avg_cost_diff_pct=round(sum(values) / len(values), 3),
                worst_case_pct=round(max(values), 3),
                best_case_pct=round(min(values), 3),
                win_rate_pct=round(wins / len(values) * 100, 1),
                sample_count=len(values),
            )
        )

    # 一次性作为基准也要放进候选 —— 否则「分批永远赢」（它的 diff 恒为 0），
    # 判断就没有对照物了
    baseline = StrategyOutcome(
        method="lump_sum",
        tranches=1,
        avg_cost_diff_pct=0.0,
        worst_case_pct=0.0,
        best_case_pct=0.0,
        win_rate_pct=0.0,
        sample_count=len(starts),
    )
    outcomes.append(baseline)
    outcomes.sort(key=lambda outcome: outcome.avg_cost_diff_pct)

    result.outcomes = outcomes
    result.sufficient_data = True

    # 容忍度随「一次性买入价本身的离散度」自适应：
    # 一次性买入价本来就忽高忽低时，分批多付一点并不值得计较；
    # 但也不能无限放宽，否则等于放弃风险约束。
    lump_mean = sum(lump_costs) / len(lump_costs) if lump_costs else 0.0
    if lump_mean > 0 and len(lump_costs) > 1:
        variance = sum((cost - lump_mean) ** 2 for cost in lump_costs) / len(lump_costs)
        dispersion = math.sqrt(variance) / lump_mean * 100
    else:
        dispersion = 0.0
    tolerance = min(
        max(dispersion, SPLIT_WORST_CASE_FLOOR_PCT), SPLIT_WORST_CASE_CAP_PCT
    )
    result.lump_dispersion_pct = round(dispersion, 2)
    result.worst_case_tolerance_pct = round(tolerance, 2)

    # 分批要同时满足两条：平均更便宜，且最坏情况在容忍度内
    splits = [outcome for outcome in outcomes if outcome.method != "lump_sum"]
    viable = [
        outcome
        for outcome in splits
        if outcome.avg_cost_diff_pct < 0 and outcome.worst_case_pct <= tolerance
    ]
    best_split = min(viable, key=lambda outcome: outcome.avg_cost_diff_pct) if viable else None
    cheapest_split = (
        min(splits, key=lambda outcome: outcome.avg_cost_diff_pct) if splits else None
    )

    if best_split is not None:
        result.recommended = best_split
        result.recommended_tranches = best_split.tranches
        result.explanation = (
            f"{_context_text(result, lookback_days)}：{best_split.label}的平均持有成本"
            f"比一次性买入低 {abs(best_split.avg_cost_diff_pct):.2f}%，"
            f"最坏情况下贵 {best_split.worst_case_pct:.2f}%（容忍度 {tolerance:.2f}%），"
            f"跑赢一次性的概率 {best_split.win_rate_pct:.0f}%，因此建议分批买入"
        )
        return result

    result.recommended = baseline
    result.recommended_tranches = 1
    if cheapest_split is None:
        detail = "没有可用的分批样本"
    elif cheapest_split.avg_cost_diff_pct >= 0:
        detail = (
            f"表现最好的分批方案（{cheapest_split.label}）平均成本仍比一次性"
            f"高 {cheapest_split.avg_cost_diff_pct:.2f}%"
        )
    else:
        detail = (
            f"表现最好的分批方案（{cheapest_split.label}）平均成本虽低 "
            f"{abs(cheapest_split.avg_cost_diff_pct):.2f}%，"
            f"但最坏情况贵 {cheapest_split.worst_case_pct:.2f}%，"
            f"超过 {tolerance:.2f}% 的容忍度"
        )
    result.explanation = f"{_context_text(result, lookback_days)}：{detail}，因此建议一次性买入"
    return result


def _context_text(result: EntryStrategyResult, lookback_days: int) -> str:
    text = (
        f"在过去 {lookback_days} 天里找到 {result.sample_count} 个与当前相似的市场环境"
        f"（当前波动率 {result.volatility_pct:.2f}%"
    )
    if result.volatility_percentile is not None:
        text += f"，处于历史 {result.volatility_percentile:.0f}% 分位"
    return text + "）"


# ==================== 带 IO 的封装 ====================


class EntryStrategyEvaluator:
    """从行情库取日线序列并回测 —— 只有这一层碰数据库"""

    #: 日线序列缓存 TTL。序列一天才变一次，没必要每 5 分钟重新聚合一遍
    #: 上百万行 tick 数据。键只有「品种 × 回看天数」两种，不会无界增长。
    SERIES_TTL_SECONDS = 1800.0

    def __init__(self, price_mapper=None, series_ttl_seconds: float | None = None) -> None:
        if price_mapper is None:
            from mapper.price_mapper import PriceMapper

            price_mapper = PriceMapper()
        self.price_mapper = price_mapper
        self.series_ttl_seconds = (
            self.SERIES_TTL_SECONDS if series_ttl_seconds is None else series_ttl_seconds
        )
        self._series_cache: dict[tuple[str, int], tuple[float, list]] = {}

    def fetch_series(self, symbol: str, lookback_days: int) -> list[tuple[date, float]]:
        """取日线序列（`get_chart_series` 会在超过 90 天时自动降采样到按天）"""
        key = (symbol, lookback_days)
        current = time.monotonic()
        cached = self._series_cache.get(key)
        if cached is not None and current - cached[0] < self.series_ttl_seconds:
            return cached[1]

        hours = lookback_days * 24
        rows = self.price_mapper.get_chart_series(symbol, hours=hours)
        series = [(timestamp.date(), float(price)) for timestamp, price in rows]
        self._series_cache[key] = (current, series)
        return series

    def invalidate_cache(self) -> None:
        self._series_cache.clear()

    def evaluate(
        self,
        symbol: str,
        current_price: float,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        horizon_days: int = DEFAULT_HORIZON_DAYS,
    ) -> EntryStrategyResult:
        try:
            series = self.fetch_series(symbol, lookback_days)
        except Exception as exc:  # noqa: BLE001
            logger.error("读取 %s 历史序列失败：%s", symbol, exc)
            series = []
        result = evaluate_entry_strategy(
            symbol,
            series,
            current_price,
            lookback_days=lookback_days,
            horizon_days=horizon_days,
        )
        logger.info(
            "建仓方式评估 %s：样本 %d，建议分 %d 批",
            symbol,
            result.sample_count,
            result.recommended_tranches,
        )
        return result
