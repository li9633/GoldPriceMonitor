import json
from datetime import datetime

from config import CHINA_TZ, SYMBOL_NAME_MAP
from mapper.model_pool_mapper import ModelPoolMapper
from mapper.price_mapper import PriceSnapshot
from service.model_pool_engine import ModelPool
from utils.logger import get_logger
from utils.trading_utils import get_trading_status_text

logger = get_logger("AIService")


class AIAnalysisService:
    """AI 行情分析服务 — 使用 GLM-4-Flash 模型"""

    SYSTEM_PROMPT = """你是一位资深黄金市场分析师，专注于上海黄金交易所 Au(T+D) 品种。
系统已触发价格报警条件（见下方【触发条件】），请你结合市场数据判断是否值得向投资者发送通知。

背景知识：
- Au(T+D) 交易时段：日盘 09:00-11:30 / 13:30-15:30，夜盘 20:00-次日02:30，周末及法定节假日休市
- 休市期间 Au(T+D) 价格停滞为收盘价，此时应以伦敦金走势为主要参考
- 伦敦金几乎 24 小时连续交易，能反映全球市场真实动向

判断原则：
- 系统报警条件已触发，默认应发送通知
- 仅在以下情况考虑不发送：数据明显异常、价格瞬间回归正常区间、报警条件为误触发
- 休市期间若伦敦金出现显著波动（涨跌幅 >0.5%），说明开盘后 Au(T+D) 大概率跟随，必须通知
- 交易时段若 Au(T+D) 与伦敦金折算价出现明显偏离，应分析原因并考虑通知
- 分析应简洁专业（不超过200字），建议应具体可操作
- urgency 设置：high=需立即关注，medium=应关注，low=仅作参考

按以下JSON格式回复（不要包含其他内容）：
{
    "should_alert": true,
    "urgency": "medium",
    "analysis": "简洁的市场分析，不超过200字",
    "suggestions": ["建议1", "建议2"]
}"""

    def __init__(self):
        self.model_pool: ModelPool | None = None
        self._providers_fingerprint: str = ""

    @property
    def enabled(self) -> bool:
        return self.model_pool is not None

    def _ensure_model_pool(self) -> bool:
        config_mapper = ModelPoolMapper()
        config_mapper.init_tables()
        providers = config_mapper.get_providers()

        if not providers:
            if self.model_pool is not None:
                logger.warning("AI 模型池配置已被清空，AI 分析已禁用")
                self.model_pool = None
            return False

        import json

        current = json.dumps(providers, sort_keys=True, default=str)
        if self.model_pool is not None and current == self._providers_fingerprint:
            return True

        self.model_pool = ModelPool(providers)
        self._providers_fingerprint = current
        has_api_key = any(p.get("api_key") for p in providers)
        if has_api_key:
            logger.info(f"AI 模型池已就绪，共 {len(providers)} 个供应商")
        else:
            logger.warning(
                f"AI 模型池已加载 {len(providers)} 个供应商，但均未配置 API Key，AI 分析仍不可用"
            )
        return has_api_key

    def analyze(
        self,
        symbol: str,
        current_price: float,
        snapshot: PriceSnapshot | None,
        london_cny: float | None = None,
        london_usd: float | None = None,
        triggered_alerts: list[str] | None = None,
    ) -> dict | None:
        if not self._ensure_model_pool():
            return None

        assert self.model_pool is not None

        prompt = self._build_prompt(
            symbol, current_price, snapshot, london_cny, london_usd, triggered_alerts
        )

        try:
            result = self.model_pool.call(self.SYSTEM_PROMPT, prompt, cache_key=symbol)
            if not result.success:
                logger.error(f"AI 分析失败：{result.error}")
                return None
            if not result.content:
                logger.error("AI 返回内容为空")
                return None
            logger.debug(
                f"AI 原始返回 [{result.provider}/{result.model}]：\n{result.content}"
            )
            parsed = self._parse_response(result.content)
            if parsed is not None:
                parsed["provider"] = result.provider
                parsed["model"] = result.model
                if result.from_cache:
                    parsed["analysis"] = (
                        f"[缓存结果，AI 实时分析暂不可用]\n{parsed['analysis']}"
                    )
                logger.info(
                    f"AI 分析结果 [{result.provider}/{result.model}]："
                    f"should_alert={parsed['should_alert']}, urgency={parsed['urgency']}"
                )
            return parsed
        except Exception as e:  # noqa: BLE001
            logger.error(f"AI 分析调用失败：{e}")
            return None

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        snapshot: PriceSnapshot | None,
        london_cny: float | None = None,
        london_usd: float | None = None,
        triggered_alerts: list[str] | None = None,
    ) -> str:
        symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)
        parts = []

        if triggered_alerts:
            parts.append(
                "【触发条件】\n系统已触发以下报警：\n"
                + "\n".join(f"- {a}" for a in triggered_alerts)
            )

        parts.append(
            f"【当前行情】\n- 品种：{symbol_name}\n- 当前价格：¥{current_price:.2f}/克"
        )

        now = datetime.now(CHINA_TZ)
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        date_str = f"{now.strftime('%Y-%m-%d')}（{weekday_names[now.weekday()]}）"
        parts.append(f"- 📅 {date_str} | {get_trading_status_text()}")

        if london_cny is not None and london_usd is not None:
            parts.append(f"- 伦敦金参考：¥{london_cny:.2f}/克 (${london_usd:.2f}/盎司)")

        if snapshot is not None:
            stats_24h = snapshot.statistics(24)
            if stats_24h:
                avg_24h = stats_24h.get("avg", 0)
                volatility = (
                    (stats_24h.get("std", 0) / avg_24h * 100) if avg_24h > 0 else 0
                )
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
                trend_parts.append(f"- 中期(24h)趋势：{self._trend_desc(trend_24h)}")
            if trend_parts:
                parts.append("【近期趋势】\n" + "\n".join(trend_parts))

            if snapshot.min_3m is not None or snapshot.min_6m is not None:
                long_term = []
                if snapshot.min_3m is not None:
                    pct = (current_price - snapshot.min_3m) / snapshot.min_3m * 100
                    long_term.append(
                        f"- 近90日最低：¥{snapshot.min_3m:.2f}（当前距低点 +{pct:.1f}%）"
                    )
                if snapshot.min_6m is not None:
                    pct = (current_price - snapshot.min_6m) / snapshot.min_6m * 100
                    long_term.append(
                        f"- 近180日最低：¥{snapshot.min_6m:.2f}（当前距低点 +{pct:.1f}%）"
                    )
                if long_term:
                    parts.append("【长期参考】\n" + "\n".join(long_term))

            recent = snapshot.prices_last_n(5)
            if len(recent) >= 2:
                price_str = " → ".join(f"¥{p:.2f}" for p in recent)
                parts.append(f"【近期价格变动】\n{price_str}")

        return "\n\n".join(parts)

    @staticmethod
    def _trend_desc(trend: dict) -> str:
        direction_map = {"up": "上涨", "down": "下跌", "stable": "横盘"}
        direction = direction_map.get(trend.get("direction", "stable"), "横盘")
        slope = trend.get("slope", 0)
        return f"{direction}（斜率 {slope:.2f}）"

    @staticmethod
    def _parse_response(content: str) -> dict | None:
        try:
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = (
                    "\n".join(lines[1:-1])
                    if lines[-1].strip() == "```"
                    else "\n".join(lines[1:])
                )
            result = json.loads(content)
            return {
                "should_alert": result.get("should_alert", False),
                "urgency": result.get("urgency", "low"),
                "analysis": result.get("analysis", ""),
                "suggestions": result.get("suggestions", []),
            }
        except json.JSONDecodeError as e:
            logger.error(f"AI 响应 JSON 解析失败：{e}，原始内容：{content[:200]}")
            return None
