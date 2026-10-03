"""LLM 措辞层 —— **只改说法，不改结论**。

这是「规则出事实，LLM 只出表述」里的后半句。硬约束写进了 system prompt：
动作、克数、价位区间已经由系统算好，模型不得修改，也不得重新计算任何数字。

因此即使模型胡说，`action` / `target_grams` / `price_band` 也不会错 —— 它只能改
`rationale` 的措辞。模型不可用时自动回退到规则生成的理由。
"""

import hashlib
import json

from models.advice import AdviceDraft
from service.advice.context import AdviceContext
from service.ai_service import AIAnalysisService
from utils.logger import get_logger

logger = get_logger("AdviceAdvisor")


class AdviceAdvisor:
    """把规则结论交给模型润色"""

    SYSTEM_PROMPT = """你是一位黄金投资顾问，负责把系统已经算好的建议解释清楚。

【硬性约束】
下面的动作、克数、价位区间、盈亏数字都已经由系统精确计算，你**不得修改、不得
重新计算、不得编造任何数字**。你只能改写措辞，让理由更容易理解。

【写作要求】
- 用中文，语气平实，不要营销腔，不要写「必涨」「稳赚」这类话
- 不超过 180 字
- 必须提及系统给出的关键数字（现价、成本价、浮盈亏、建议克数等）
- 如果建议是观望或持有，要说清楚在等什么条件

按以下 JSON 格式回复（不要包含其他内容）：
{
    "rationale": "改写后的理由"
}"""

    def __init__(self, ai_service: AIAnalysisService | None = None) -> None:
        self.ai_service = ai_service or AIAnalysisService()

    def phrase(self, ctx: AdviceContext, draft: AdviceDraft) -> tuple[str, str]:
        """返回 `(rationale, model_info)`；模型不可用时原样返回规则措辞"""
        prompt = self._build_prompt(ctx, draft)
        cache_key = "advice|" + hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
        result = self.ai_service.complete(self.SYSTEM_PROMPT, prompt, cache_key)
        if result is None:
            logger.info("AI 不可用，建议使用规则措辞")
            return draft.rationale, ""

        rationale = self._parse(result["content"])
        if not rationale:
            return draft.rationale, ""
        return rationale, f"{result['provider']}/{result['model']}"

    @staticmethod
    def _parse(content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("建议措辞返回的不是合法 JSON，已回退规则措辞")
            return ""
        rationale = str(data.get("rationale") or "").strip()
        return rationale

    @staticmethod
    def _build_prompt(ctx: AdviceContext, draft: AdviceDraft) -> str:
        ind = ctx.indicators
        position = ctx.position
        lines: list[str] = [
            "【系统已算好的结论】（不得修改）",
            f"- 建议动作：{draft.action.value}",
        ]
        if draft.target_grams is not None:
            lines.append(f"- 建议克数：{draft.target_grams} 克")
        if draft.price_band_low is not None and draft.price_band_high is not None:
            lines.append(
                f"- 建议价位区间：¥{draft.price_band_low:.2f} ~ ¥{draft.price_band_high:.2f}"
            )
        lines.append(f"- 置信度：{draft.confidence}")

        lines.append("")
        lines.append("【规则给出的理由（供参考，请改写得更清楚）】")
        lines.append(draft.rationale or "（无）")

        lines.append("")
        lines.append("【行情】")
        lines.append(f"- 品种：{ctx.symbol_name}（{ctx.symbol}）")
        lines.append(f"- 现价：¥{ind.current_price:.2f}/克")
        if ind.min_3m is not None and ind.pct_from_3m_low is not None:
            lines.append(f"- 近 90 日低点：¥{ind.min_3m:.2f}（当前 {ind.pct_from_3m_low:+.2f}%）")
        if ind.min_6m is not None and ind.pct_from_6m_low is not None:
            lines.append(f"- 近 180 日低点：¥{ind.min_6m:.2f}（当前 {ind.pct_from_6m_low:+.2f}%）")
        if ind.avg_24h is not None:
            lines.append(
                f"- 24 小时：均价 ¥{ind.avg_24h:.2f} / 最高 ¥{ind.max_24h:.2f} / "
                f"最低 ¥{ind.min_24h:.2f}"
            )
        if ind.volatility_pct is not None:
            lines.append(f"- 24 小时波动率：{ind.volatility_pct:.2f}%")
        if ind.trend_24h_direction:
            lines.append(f"- 中期趋势：{ind.trend_24h_direction}")
        if ind.london_cny is not None:
            lines.append(f"- 伦敦金参考：¥{ind.london_cny:.2f}/克")

        lines.append("")
        lines.append("【持仓】")
        if position.total_grams > 0:
            lines.append(
                f"- 持仓 {position.total_grams}g，成本价 ¥{position.avg_cost:.2f}，"
                f"浮动盈亏 ¥{position.unrealized_pnl or 0:.2f}"
                f"（{position.unrealized_pnl_pct or 0:+.2f}%）"
            )
        else:
            lines.append("- 当前没有持仓")

        ratio = ctx.position_ratio_pct()
        if ratio is not None:
            lines.append(f"- 持仓市值占总可投资金：{ratio:.1f}%")

        if ctx.plans:
            lines.append("")
            lines.append("【购买计划】")
            for state in ctx.plans:
                progress = state.progress
                lines.append(
                    f"- 计划 #{progress.plan_id}：{progress.filled_grams}/"
                    f"{progress.target_grams}g（{progress.progress_pct:.0f}%），"
                    f"分 {progress.tranches} 批"
                )

        lines.append("")
        lines.append("【命中信号】")
        for signal in draft.signals:
            lines.append(f"- [{signal.severity}] {signal.summary}")

        return "\n".join(lines)
