import json

from config import AI_CONFIG, AI_PROVIDERS, SYMBOL_NAME_MAP
from mapper.price_mapper import PriceSnapshot
from service.model_pool import ModelPool
from utils.logger import get_logger

logger = get_logger("AIService")


class AIAnalysisService:
    """AI 行情分析服务 — 使用 GLM-4-Flash 模型"""

    SYSTEM_PROMPT = """你是一位资深黄金市场分析师，专注于上海黄金交易所 Au(T+D) 品种。
请根据提供的市场数据，判断当前是否值得向投资者发送通知，并给出分析。

通知原则：
- 仅在有明确交易信号或显著风险时通知（如突破关键位、趋势反转、异常波动等）
- 市场平稳运行时不要通知，避免干扰投资者
- 分析应简洁专业，建议应具体可操作

按以下JSON格式回复（不要包含其他内容）：
{
    "should_alert": true,
    "urgency": "medium",
    "analysis": "简洁的市场分析，不超过200字",
    "suggestions": ["建议1", "建议2"]
}"""

    def __init__(self):
        self.model_pool = ModelPool(AI_PROVIDERS)
        self.enabled = AI_CONFIG["enabled"] and any(
            p.get("api_key") for p in AI_PROVIDERS)

    def analyze(self, symbol: str, current_price: float,
                snapshot: PriceSnapshot | None,
                london_cny: float | None = None,
                london_usd: float | None = None) -> dict | None:
        if not self.enabled:
            return None

        prompt = self._build_prompt(
            symbol, current_price, snapshot, london_cny, london_usd)

        try:
            result = self.model_pool.call(
                self.SYSTEM_PROMPT, prompt, cache_key=symbol)
            if not result.success:
                logger.error(f"AI 分析失败：{result.error}")
                return None
            logger.debug(f"AI 原始返回 [{result.provider}/{result.model}]：\n{result.content}")
            parsed = self._parse_response(result.content)
            if parsed is not None:
                parsed["provider"] = result.provider
                parsed["model"] = result.model
                if result.from_cache:
                    parsed["analysis"] = (
                        f"[缓存结果，AI 实时分析暂不可用]\n{parsed['analysis']}")
                logger.info(
                    f"AI 分析结果 [{result.provider}/{result.model}]："
                    f"should_alert={parsed['should_alert']}, urgency={parsed['urgency']}")
            return parsed
        except Exception as e:  # noqa: BLE001
            logger.error(f"AI 分析调用失败：{e}")
            return None

    def _build_prompt(self, symbol: str, current_price: float,
                      snapshot: PriceSnapshot | None,
                      london_cny: float | None = None,
                      london_usd: float | None = None) -> str:
        symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)
        parts = [f"【当前行情】\n- 品种：{symbol_name}\n- 当前价格：¥{current_price:.2f}/克"]

        if london_cny is not None and london_usd is not None:
            parts.append(f"- 伦敦金参考：¥{london_cny:.2f}/克 (${london_usd:.2f}/盎司)")

        if snapshot is not None:
            stats_24h = snapshot.statistics(24)
            if stats_24h:
                avg_24h = stats_24h.get('avg', 0)
                volatility = (stats_24h.get('std', 0) /
                              avg_24h * 100) if avg_24h > 0 else 0
                parts.append(
                    "【统计指标】\n"
                    f"- 24小时均价：¥{avg_24h:.2f}\n"
                    f"- 24小时最高：¥{stats_24h.get('max', 0):.2f}\n"
                    f"- 24小时最低：¥{stats_24h.get('min', 0):.2f}\n"
                    f"- 24小时波动率：{volatility:.2f}%\n"
                    f"- 数据量：{stats_24h.get('count', 0)}条"
                )

            ma_parts = []
            for period in [5, 10, 20]:
                ma_val = snapshot.ma(period)
                if ma_val is not None:
                    ma_parts.append(f"- {period}周期均线：¥{ma_val:.2f}")
            if ma_parts:
                parts.append("【均线指标】\n" + "\n".join(ma_parts))

            trend_6h = snapshot.trend(6)
            trend_24h = snapshot.trend(24)
            trend_parts = []
            if trend_6h:
                trend_parts.append(f"- 短期(6h)趋势：{self._trend_desc(trend_6h)}")
            if trend_24h:
                trend_parts.append(
                    f"- 中期(24h)趋势：{self._trend_desc(trend_24h)}")
            if trend_parts:
                parts.append("【近期趋势】\n" + "\n".join(trend_parts))

            if snapshot.min_3m is not None or snapshot.min_6m is not None:
                long_term = []
                if snapshot.min_3m is not None:
                    pct = (current_price - snapshot.min_3m) / \
                        snapshot.min_3m * 100
                    long_term.append(
                        f"- 近90日最低：¥{snapshot.min_3m:.2f}（当前距低点 +{pct:.1f}%）")
                if snapshot.min_6m is not None:
                    pct = (current_price - snapshot.min_6m) / \
                        snapshot.min_6m * 100
                    long_term.append(
                        f"- 近180日最低：¥{snapshot.min_6m:.2f}（当前距低点 +{pct:.1f}%）")
                if long_term:
                    parts.append("【长期参考】\n" + "\n".join(long_term))

            recent = snapshot.prices_last_n(5)
            if len(recent) >= 2:
                price_str = " → ".join(f"¥{p:.2f}" for p in recent)
                parts.append(f"【近期价格变动】\n{price_str}")

        return "\n\n".join(parts)

    @staticmethod
    def _trend_desc(trend: dict) -> str:
        direction_map = {'up': '上涨', 'down': '下跌', 'stable': '横盘'}
        direction = direction_map.get(trend.get('direction', 'stable'), '横盘')
        slope = trend.get('slope', 0)
        return f"{direction}（斜率 {slope:.2f}）"

    @staticmethod
    def _parse_response(content: str) -> dict | None:
        try:
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(
                    lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            result = json.loads(content)
            return {
                "should_alert": result.get("should_alert", False),
                "urgency": result.get("urgency", "low"),
                "analysis": result.get("analysis", ""),
                "suggestions": result.get("suggestions", [])
            }
        except json.JSONDecodeError as e:
            logger.error(f"AI 响应 JSON 解析失败：{e}，原始内容：{content[:200]}")
            return None