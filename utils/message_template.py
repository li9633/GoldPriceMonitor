import re
from datetime import datetime
from pathlib import Path

from config import CHINA_TZ, DEBUG, SYMBOL_NAME_MAP


class MessageTemplate:
    """消息模板管理 - 支持企业微信 markdown 和邮件 HTML 格式"""

    # 企业微信 Markdown V2 模板
    # 修改点：在“当前价格”下方增加了 {london_gold_info} 占位符
    WECHAT_MARKDOWN_TEMPLATE = """## <font color="warning">[报警] 黄金价格监控</font>

**品种**：{symbol_name}
**当前价格**：<font color="{price_color}">{price}</font>
{london_gold_info}
**报警时间**：{time}

### <font color="comment">AI 分析</font>
{conditions}

### <font color="info">AI 操作建议</font>
{suggestions}
{debug_notice}
{ai_model_info}
---
*系统持续监控中，请及时处理*"""

    _email_html_template: str | None = None

    @classmethod
    def _load_email_html_template(cls) -> str:
        if cls._email_html_template is not None:
            return cls._email_html_template
        template_dir = Path(__file__).parent.parent / "templates"
        template_path = template_dir / "email_alert.html"
        with open(template_path, encoding="utf-8") as f:
            cls._email_html_template = f.read()
        return cls._email_html_template

    @classmethod
    def _escape_markdown(cls, text: str) -> str:
        """转义企业微信 markdown 特殊字符"""
        if not isinstance(text, str):
            return str(text)
        special_chars = r'([\\*_`\[\]()~>#\+\-=|{}.!])'
        return re.sub(special_chars, r'\\\1', text)

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
            ">": "&gt;"
        }
        for key, value in html_escape_table.items():
            text = text.replace(key, value)
        return text

    @classmethod
    def format_alert(cls, symbol: str, price: float,
                     conditions: list[str], suggestions: list[str],
                     template_type: str = "alert",
                     avg_price: float | None = None,
                     extra_info: dict | None = None) -> str:
        """
        格式化报警消息
        :param extra_info: 额外信息字典，例如 {'london_gold_usd': 2300, 'london_gold_cny': 530.5}
        """

        if template_type == "email":
            template = cls._load_email_html_template()
        elif template_type == "markdown":
            template = cls.WECHAT_MARKDOWN_TEMPLATE
        else:
            # 默认或其他类型 fallback 到 markdown
            template = cls.WECHAT_MARKDOWN_TEMPLATE

        # 计算主价格颜色
        if avg_price is None:
            avg_price = price
        price_color = "#d32f2f" if price >= avg_price else "#1976d2"

        # --- 构建伦敦金信息显示字符串 ---
        london_gold_info_str = ""
        if extra_info and 'london_gold_cny' in extra_info:
            cny_price = extra_info['london_gold_cny']
            usd_price = extra_info.get('london_gold_usd', 'N/A')

            if template_type == "markdown":
                london_gold_info_str = f"\n**伦敦金参考**：<font color=\"#1976d2\">¥{cny_price}/g</font> <font>~</font> <font color=\"#1976d2\">(${usd_price})</font>"

            elif template_type == "email":
                # 邮件 HTML: 使用 CSS 类或内联样式
                london_gold_info_str = f'<div class="london-price">伦敦金参考：¥{cny_price}/g (${usd_price})</div>'

        # --- 格式化条件和建议 ---
        if template_type == "markdown":
            conditions_str = "\n".join(
                [f"- {cls._escape_markdown(c)}" for c in conditions])
            suggestions_str = "\n".join(
                [f"- {cls._escape_markdown(s)}" for s in suggestions]) if suggestions else "- 请密切关注市场动态"

        elif template_type == "email":
            conditions_str = "\n".join(
                [f'<div class="condition-item">{cls._escape_html(c)}</div>' for c in conditions])
            suggestions_str = "\n".join(
                [f'<div class="suggestion-item">{cls._escape_html(s)}</div>' for s in suggestions]) if suggestions else '<div class="suggestion-item">请密切关注市场动态</div>'
        else:
            # 默认文本格式
            conditions_str = "\n".join([f"  - {c}" for c in conditions])
            suggestions_str = "\n".join(
                [f"  • {s}" for s in suggestions]) if suggestions else "  • 请密切关注市场动态"
            price_color = "#1976d2"

        # 获取品种名称
        symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)
        display_name = cls._escape_markdown(symbol_name) if template_type == "markdown" else symbol_name
        display_price = f"{price:.2f}" if isinstance(price, (int, float)) else str(price)
        display_time = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        display_year = str(datetime.now(CHINA_TZ).year)

        debug_notice = ""
        if DEBUG:
            if template_type == "markdown":
                debug_notice = "> <font color=\"comment\">[开发环境] 此消息为测试数据，不代表最终结果</font>"
            elif template_type == "email":
                debug_notice = '<div class="debug-notice">[开发环境] 此消息为测试数据，不代表最终结果</div>'

        ai_model_info_str = ""
        if extra_info and extra_info.get("ai_model_info"):
            if template_type == "markdown":
                ai_model_info_str = f"> <font color=\"comment\">分析模型：{extra_info['ai_model_info']}</font>"
            elif template_type == "email":
                ai_model_info_str = (
                    f'<div class="model-info">分析模型：{extra_info["ai_model_info"]}</div>')

        # 邮件模板使用 {{placeholder}} 语法，通过 replace 渲染
        if template_type == "email":
            return (template
                    .replace("{{symbol_name}}", display_name)
                    .replace("{{price}}", display_price)
                    .replace("{{price_color}}", price_color)
                    .replace("{{london_gold_info}}", london_gold_info_str)
                    .replace("{{time}}", display_time)
                    .replace("{{year}}", display_year)
                    .replace("{{conditions}}", conditions_str)
                    .replace("{{suggestions}}", suggestions_str)
                    .replace("{{debug_notice}}", debug_notice)
                    .replace("{{ai_model_info}}", ai_model_info_str))

        # Markdown 模板使用 {placeholder} 语法，通过 format 渲染
        return template.format(
            symbol_name=display_name,
            price=display_price,
            price_color=price_color,
            london_gold_info=london_gold_info_str,
            time=display_time,
            year=display_year,
            conditions=conditions_str,
            suggestions=suggestions_str,
            debug_notice=debug_notice,
            ai_model_info=ai_model_info_str
        )