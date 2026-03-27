
import requests
from typing import List
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from config import EMAIL_CONFIG, WECHAT_WORK_CONFIG, SYMBOL_NAME_MAP
from message_template import MessageTemplate
from logger import get_logger
logger = get_logger("Notifier")


class Notifier:
    def __init__(self):
        self.email_config = EMAIL_CONFIG
        self.wechat_config = WECHAT_WORK_CONFIG

    def send_alert(self, symbol: str, current_price: float,
                   alert_messages: List[str],
                   suggestions: List[str] = None) -> bool:
        """统一发送报警，支持多种方式"""
        results = []
        suggestions = suggestions or []

        logger.info(f"发送报警通知，品种：{symbol}, 价格：{current_price}")

        # 发送邮件
        if self.email_config.get("enabled", True):
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="email")
            results.append(self._send_email_alert(
                symbol, current_price, message))

        # 发送企业微信
        if self.wechat_config.get("enabled", False):
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="alert")
            results.append(self._send_wechat_work_alert(message))

        return any(results)

    def _send_email_alert(self, symbol: str, current_price: float, message: str) -> bool:
        """发送邮件"""
        try:
            subject = f"黄金价格监控报警 - {SYMBOL_NAME_MAP.get(symbol, symbol)} - {current_price}"
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['receiver_email']

            server = smtplib.SMTP(
                self.email_config['smtp_server'], self.email_config['smtp_port'])
            server.starttls()
            server.login(
                self.email_config['sender_email'], self.email_config['sender_password'])
            server.send_message(msg)
            server.quit()
            logger.info(f"[{datetime.now()}] 邮件发送成功")
            return True
        except Exception as e:
            logger.error(f"[{datetime.now()}] 邮件发送失败: {e}")
            return False

    def _send_wechat_work_alert(self, message: str) -> bool:
        """发送企业微信机器人消息"""
        if not self.wechat_config.get("webhook_url"):
            return False

        try:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }

            response = requests.post(
                self.wechat_config["webhook_url"],
                json=payload,
                timeout=10
            )

            if response.status_code == 200 and response.json().get("errcode") == 0:
                logger.info(f"[{datetime.now()}] 企业微信消息发送成功")
                return True
            else:
                logger.error(f"[{datetime.now()}] 企业微信消息发送失败: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[{datetime.now()}] 企业微信发送异常: {e}")
            return False

    def _send_wechat_work_markdown(self, message: str) -> bool:
        """发送企业微信 markdown 格式消息"""
        if not self.wechat_config.get("webhook_url"):
            return False

        # 修复：将 replace 操作移到 f-string 外部
        formatted_message = message.replace('\n', '\n\n')
        markdown_content = f"""# 🚨 黄金价格监控报警
            
    {formatted_message}
        """

        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": markdown_content
                }
            }

            response = requests.post(
                self.wechat_config["webhook_url"],
                json=payload,
                timeout=10
            )

            return response.status_code == 200 and response.json().get("errcode") == 0
        except Exception as e:
            logger.error(f"[{datetime.now()}] 企业微信 markdown 发送异常：{e}")
            return False
