from datetime import datetime
from typing import List
from config import SYMBOL_NAME_MAP


class MessageTemplate:
    """消息模板管理 - 带操作建议"""

    # 简洁版模板
    ALERT_TEMPLATE = """【价格报警】{symbol_name}
当前价格：{price}
报警时间：{time}
触发条件：
{conditions}

💡 操作建议：
{suggestions}"""

    # 邮件详细版模板
    EMAIL_TEMPLATE = """================================
黄金价格监控报警
================================
监控品种：{symbol_name}
当前价格：{price}
报警时间：{time}

触发条件：
{conditions}

--------------------------------
操作建议：
{suggestions}
--------------------------------
请及时处理，系统持续监控中。
================================"""

    # 企业微信 Markdown 模板
    WECHAT_MARKDOWN_TEMPLATE = """## 价格报警

**品种**：{symbol_name}
**价格**：{price}
**时间**：{time}

**触发条件：**
{conditions}

**操作建议：**
{suggestions}"""

    @classmethod
    def format_alert(cls, symbol: str, price: float,
                     conditions: List[str], suggestions: List[str],
                     template_type: str = "alert") -> str:
        """格式化报警消息
        
        Args:
            symbol: 品种代码
            price: 当前价格
            conditions: 触发条件列表
            suggestions: 操作建议列表
            template_type: 模板类型 (alert/email/markdown)
        
        Returns:
            格式化后的消息字符串
        """
        template = getattr(
            cls, f"{template_type.upper()}_TEMPLATE", cls.ALERT_TEMPLATE)

        return template.format(
            symbol_name=SYMBOL_NAME_MAP.get(symbol, symbol),
            price=f"{price:.2f}" if isinstance(
                price, (int, float)) else str(price),
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            conditions="\n".join([f"  - {c}" for c in conditions]),
            suggestions="\n".join(
                [f"  • {s}" for s in suggestions]) if suggestions else "  • 请密切关注市场动态"
        )
