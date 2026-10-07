import re
from pathlib import Path

from channels.base import ADVICE_KINDS, NotificationData
from config import DEBUG
from utils.time_utils import now, now_str


def _get_symbol_name_map() -> dict[str, str]:
    from service.system_settings_service import SystemSettingsService

    return SystemSettingsService().get_symbol_name_map()


class MessageTemplate:
    """消息模板管理 —— 企业微信 markdown 与邮件 HTML 两种建议消息"""

    _email_advice_template: str | None = None

    #: 建议动作 → 中文标签（展示层职责，不放进数据模型）
    ACTION_LABELS = {
        "BUY_NOW": "可以买入",
        "BUY_PARTIAL": "建议分批买入",
        "WAIT": "建议观望",
        "AVOID": "不建议买入",
        "HOLD": "继续持有",
        "ADD": "建议补仓",
        "TAKE_PROFIT": "建议分批止盈",
        "STOP_LOSS": "建议减仓止损",
    }

    #: 建议动作 → 颜色（红涨绿跌之外，用金色标买入、蓝色标止盈、红色标风险）
    ACTION_COLORS = {
        "BUY_NOW": "#d4a017",
        "BUY_PARTIAL": "#d4a017",
        "ADD": "#d4a017",
        "TAKE_PROFIT": "#1976d2",
        "STOP_LOSS": "#d32f2f",
    }

    # 企业微信 Markdown 建议模板
    WECHAT_ADVICE_TEMPLATE = """## <font color="info">[建议] 黄金持仓建议</font>

**品种**：{symbol_name}
**当前价格**：<font color="{price_color}">{price}</font>
{london_gold_info}
**建议动作**：<font color="{action_color}">{action_label}</font>
**建议数量**：{target_grams}
**建议价位**：{price_band}
**持仓状态**：{position_info}
{valuation_note}
**生成时间**：{time}

### <font color="comment">判断依据</font>
{signals}

### <font color="comment">说明</font>
{rationale}
{debug_notice}
{model_info}
---
*建议由规则计算生成，仅供参考，不构成投资建议*"""

    #: 非 advice 类消息的标题（volatility / digest / reopen_gap …）。
    #: 新 kind 只要在这里登记标题，渠道与通用渲染器零改动即可投递。
    KIND_TITLES = {
        "volatility": "黄金价格波动提醒",
        "digest": "黄金每日行情摘要",
        "reopen_gap": "节后开盘提示",
    }

    # 企业微信 Markdown 通用模板（fields 逐行展开）。
    # 注意：品种 / 价格行由 `format_generic` 按「是否存在」拼接成完整行传入，
    # 这里不要再写 **品种**/**当前价格** 前缀 —— 否则会渲染出「品种：品种：…」
    WECHAT_GENERIC_TEMPLATE = """## <font color="info">[{title}]</font>

{symbol_line}{price_line}{field_lines}
**生成时间**：{time}
{debug_notice}
---
*消息由系统自动生成，仅供参考，不构成投资建议*"""

    @classmethod
    def format(cls, kind: str, data, template_type: str = "markdown") -> str:
        """按消息类型分发渲染。

        advice/review 走建议模板；其余 kind 走通用模板（`fields` 逐行展开）。
        """
        if kind in ADVICE_KINDS:
            return cls.format_advice(data, template_type=template_type)
        return cls.format_generic(data, template_type=template_type)

    @classmethod
    def kind_title(cls, kind: str) -> str:
        return cls.KIND_TITLES.get(kind, kind)

    @classmethod
    def format_generic(cls, data, template_type: str = "markdown") -> str:
        """渲染非建议类消息：fields 里的键值对逐行展开"""
        title = cls.kind_title(data.kind)
        display_price = cls._format_price(data.current_price)
        debug_notice = (
            '<div class="debug-notice">[开发环境] 此消息为测试数据</div>'
            if template_type == "email"
            else '> <font color="comment">[开发环境] 此消息为测试数据</font>'
        ) if DEBUG else ""
        display_time = now_str("%Y-%m-%d %H:%M:%S")

        if template_type == "email":
            fields_html = "\n".join(
                f'<div class="meta">{cls._escape_html(label)}：'
                f"{cls._escape_html(value)}</div>"
                for label, value in data.fields.items()
            )
            symbol_html = (
                f'<div class="meta">品种：{cls._escape_html(data.symbol_name)}</div>'
                if data.symbol_name
                else ""
            )
            price_html = (
                f'<div class="meta">当前价格：¥{display_price}/g</div>'
                if display_price
                else ""
            )
            return (
                "<html><body style='font-family: sans-serif; max-width: 640px'>"
                f"<h2>{cls._escape_html(title)}</h2>"
                f"{symbol_html}{price_html}{fields_html}"
                f"<div class='meta'>生成时间：{display_time}</div>"
                f"{debug_notice}"
                "<hr/><small>消息由系统自动生成，仅供参考，不构成投资建议</small>"
                "</body></html>"
            )

        field_lines = "\n".join(
            f"**{cls._escape_markdown(label)}**：{cls._escape_markdown(value)}"
            for label, value in data.fields.items()
        )
        symbol_line = (
            f"**品种**：{cls._escape_markdown(data.symbol_name)}\n"
            if data.symbol_name
            else ""
        )
        price_line = f"**当前价格**：¥{display_price}/g\n" if display_price else ""
        return cls.WECHAT_GENERIC_TEMPLATE.format(
            title=cls._escape_markdown(title),
            symbol_line=symbol_line,
            price_line=price_line,
            field_lines=field_lines,
            time=display_time,
            debug_notice=debug_notice,
        )

    @classmethod
    def _format_price(cls, price) -> str:
        """价格展示：非正值（未提供）返回空串"""
        if isinstance(price, (int, float)) and price > 0:
            return f"{price:.2f}"
        if isinstance(price, str) and price:
            return price
        return ""

    @classmethod
    def _load_email_advice_template(cls) -> str:
        if cls._email_advice_template is not None:
            return cls._email_advice_template
        template_path = Path(__file__).parent.parent / "templates" / "email_advice.html"
        with open(template_path, encoding="utf-8") as f:
            cls._email_advice_template = f.read()
        return cls._email_advice_template

    @classmethod
    def format_advice(cls, data: NotificationData, template_type: str = "markdown") -> str:
        """渲染建议消息。

        动作、数量、价位区间与持仓上下文。
        """
        advice = data.advice
        if advice is None:
            raise ValueError("format_advice 需要 NotificationData.advice 载荷")

        symbol_name = _get_symbol_name_map().get(data.symbol, data.symbol)
        price = data.current_price
        price_color = "#d4a017"
        action_label = cls.ACTION_LABELS.get(advice.action, advice.action)
        action_color = cls.ACTION_COLORS.get(advice.action, "#8c7a5c")

        display_price = f"{price:.2f}" if isinstance(price, (int, float)) else str(price)

        target_text = (
            f"{advice.target_grams} 克" if advice.target_grams else "—（本次不涉及数量）"
        )
        if advice.price_band_low is not None and advice.price_band_high is not None:
            band_text = f"¥{advice.price_band_low:.2f} ~ ¥{advice.price_band_high:.2f}"
        else:
            band_text = "—"

        if advice.total_grams:
            if advice.avg_cost is not None and advice.unrealized_pnl_pct is not None:
                position_text = (
                    f"{advice.total_grams}g，成本价 ¥{advice.avg_cost:.2f}"
                    f"（浮动 {advice.unrealized_pnl_pct:+.2f}%）"
                )
            else:
                position_text = f"{advice.total_grams}g"
        else:
            position_text = "暂无持仓"

        # 伦敦金参考
        london_str = ""
        extra_info = data.extra_info or {}
        if extra_info.get("london_gold_cny") is not None:
            cny = extra_info["london_gold_cny"]
            usd = extra_info.get("london_gold_usd", "N/A")
            if template_type == "email":
                london_str = (
                    f'<div class="meta">伦敦金参考：¥{cny}/g（${usd}）</div>'
                )
            else:
                london_str = (
                    f'\n**伦敦金参考**：¥{cny}/g（${usd}）'
                )

        # 估值口径说明（INTL_ONLY：按国际金折算价估算持仓）
        valuation_note = ""
        if extra_info.get("valuation_note"):
            note_text = cls._escape_html(str(extra_info["valuation_note"]))
            if template_type == "email":
                valuation_note = f'<div class="meta">＊{note_text}</div>'
            else:
                valuation_note = f'\n> <font color="comment">＊{note_text}</font>'

        debug_notice = ""
        if DEBUG:
            debug_notice = (
                '<div class="debug-notice">[开发环境] 此消息为测试数据</div>'
                if template_type == "email"
                else '> <font color="comment">[开发环境] 此消息为测试数据</font>'
            )

        model_info = ""
        if extra_info.get("ai_model_info"):
            if template_type == "email":
                model_info = (
                    f'<div class="model-info">措辞模型：{extra_info["ai_model_info"]}</div>'
                )
            else:
                model_info = (
                    f'> <font color="comment">措辞模型：{extra_info["ai_model_info"]}</font>'
                )

        display_time = now_str("%Y-%m-%d %H:%M:%S")

        if template_type == "email":
            signals_html = "\n".join(
                f'<div class="condition-item">{cls._escape_html(s)}</div>'
                for s in advice.signals
            ) or '<div class="condition-item">（无）</div>'
            return (
                cls._load_email_advice_template()
                .replace("{{symbol_name}}", cls._escape_html(symbol_name))
                .replace("{{price}}", display_price)
                .replace("{{london_gold_info}}", london_str)
                .replace("{{action_label}}", cls._escape_html(action_label))
                .replace("{{action_color}}", action_color)
                .replace("{{target_grams}}", cls._escape_html(target_text))
                .replace("{{price_band}}", cls._escape_html(band_text))
                .replace("{{position_info}}", cls._escape_html(position_text))
                .replace("{{valuation_note}}", valuation_note)
                .replace("{{time}}", display_time)
                .replace("{{year}}", str(now().year))
                .replace("{{signals}}", signals_html)
                .replace(
                    "{{rationale}}", cls._escape_html(advice.rationale or "（无）")
                )
                .replace("{{debug_notice}}", debug_notice)
                .replace("{{model_info}}", model_info)
            )

        signals_md = (
            "\n".join(f"- {cls._escape_markdown(s)}" for s in advice.signals)
            or "- （无）"
        )
        return cls.WECHAT_ADVICE_TEMPLATE.format(
            symbol_name=cls._escape_markdown(symbol_name),
            price=display_price,
            price_color=price_color,
            london_gold_info=london_str,
            action_label=action_label,
            action_color=action_color,
            target_grams=target_text,
            price_band=band_text,
            position_info=position_text,
            time=display_time,
            signals=signals_md,
            rationale=cls._escape_markdown(advice.rationale or "（无）"),
            valuation_note=valuation_note,
            debug_notice=debug_notice,
            model_info=model_info,
        )

    #: 企业微信 markdown 里**真正有语法含义**、必须转义的字符。
    #:
    #: 早先这里把 `.` `+` `-` `!` `=` 等也一并转义了，结果「¥911.00」「+1.22%」会变成
    #: 「¥911\.00」「\+1.22%」。企业微信并不解析反斜杠转义（它的 markdown 是简化版），
    #: 所以那些反斜杠会**原样显示**给用户，价格和百分比看起来就很脏。
    #: 只保留真正会引起格式变化的字符。
    _MARKDOWN_SPECIALS = r"([\\*_`\[\]#])"

    @classmethod
    def _escape_markdown(cls, text: str) -> str:
        """转义企业微信 markdown 的特殊字符"""
        if not isinstance(text, str):
            return str(text)
        return re.sub(cls._MARKDOWN_SPECIALS, r"\\\1", text)

    @classmethod
    def _escape_html(cls, text: str) -> str:
        """转义 HTML 特殊字符"""
        if not isinstance(text, str):
            return str(text)
        html_escape_table = {
            "&": "&amp;",
            '"': "&quot;",
            "'": "&apos;",
            "<": "&lt;",
            ">": "&gt;",
        }
        for key, value in html_escape_table.items():
            text = text.replace(key, value)
        return text
