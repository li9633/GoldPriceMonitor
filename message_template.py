from datetime import datetime
from typing import List
from config import SYMBOL_NAME_MAP
import re


class MessageTemplate:
    """消息模板管理 - 支持企业微信 markdown 和邮件 HTML 格式"""

    # 企业微信 Markdown V2 模板
    WECHAT_MARKDOWN_TEMPLATE = """## <font color="warning">🚨 黄金价格监控报警</font>

**品种**：{symbol_name}
**当前价格**：<font color="{price_color}">{price}</font>
**报警时间**：{time}

### <font color="comment">触发条件</font>
{conditions}

### <font color="info">💡 操作建议</font>
{suggestions}

---
*系统持续监控中，请及时处理*"""

    # 邮件 HTML 模板（优化版）
    EMAIL_HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
            .header h1 {{ margin: 0; font-size: 24px; }}
            .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #e0e0e0; }}
            .price-box {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid {price_color}; }}
            .price {{ font-size: 28px; font-weight: bold; color: {price_color}; }}
            .section {{ margin: 15px 0; }}
            .section-title {{ font-weight: bold; color: #333; border-bottom: 2px solid #667eea; padding-bottom: 5px; }}
            .condition-item {{ background: white; padding: 10px; margin: 8px 0; border-radius: 5px; border-left: 3px solid #ff9800; }}
            .suggestion-item {{ background: #e3f2fd; padding: 10px; margin: 8px 0; border-radius: 5px; border-left: 3px solid #2196f3; }}
            .footer {{ background: #f5f5f5; padding: 15px; text-align: center; color: #666; border-radius: 0 0 10px 10px; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚨 黄金价格监控报警</h1>
            </div>
            <div class="content">
                <div class="price-box">
                    <div><strong>品种：</strong>{symbol_name}</div>
                    <div class="price">当前价格：{price}</div>
                    <div><strong>报警时间：</strong>{time}</div>
                </div>
                
                <div class="section">
                    <div class="section-title">📋 触发条件</div>
                    {conditions}
                </div>
                
                <div class="section">
                    <div class="section-title">💡 操作建议</div>
                    {suggestions}
                </div>
            </div>
            <div class="footer">
                <p>系统持续监控中，请及时处理</p>
                <p>黄金价格监控系统 © {year}</p>
            </div>
        </div>
    </body>
    </html>
    """

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
                     conditions: List[str], suggestions: List[str],
                     template_type: str = "alert",
                     avg_price: float = None) -> str:
        """格式化报警消息
        
        Args:
            symbol: 品种代码
            price: 当前价格
            conditions: 触发条件列表
            suggestions: 操作建议列表
            template_type: 模板类型 (alert/email/markdown)
            avg_price: 平均价格，用于判断颜色（可选）
        
        Returns:
            格式化后的消息字符串
        """
        template = getattr(
            cls, f"{template_type.upper()}_TEMPLATE", cls.WECHAT_MARKDOWN_TEMPLATE)

        # 计算价格颜色
        if avg_price is None:
            avg_price = price
        price_color = "#d32f2f" if price >= avg_price else "#1976d2"  # 红色/蓝色

        # 根据不同模板类型格式化内容
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
            conditions_str = "\n".join([f"  - {c}" for c in conditions])
            suggestions_str = "\n".join(
                [f"  • {s}" for s in suggestions]) if suggestions else "  • 请密切关注市场动态"
            price_color = "#1976d2"

        return template.format(
            symbol_name=cls._escape_markdown(SYMBOL_NAME_MAP.get(
                symbol, symbol)) if template_type == "markdown" else SYMBOL_NAME_MAP.get(symbol, symbol),
            price=f"{price:.2f}" if isinstance(
                price, (int, float)) else str(price),
            price_color=price_color,
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            year=datetime.now().year,
            conditions=conditions_str,
            suggestions=suggestions_str
        )
