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
        """
        统一发送报警通知，支持降级机制
        优先使用企业微信，失败后降级使用邮件
        """
        suggestions = suggestions or []
        symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)

        logger.info("========== 开始发送报警通知 ==========")
        logger.info(f"品种：{symbol_name}, 价格：{current_price}")
        logger.info(f"报警信息：{alert_messages}")

        # 1. 优先尝试企业微信通知
        wechat_success = False
        if self.wechat_config.get("enabled", False) and self.wechat_config.get("webhook_url"):
            logger.info("[通知策略] 尝试使用企业微信发送通知...")
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="alert")
            wechat_success = self._send_wechat_work_alert(message)

            if wechat_success:
                logger.info("[通知结果] 企业微信通知成功，无需降级邮件通知")
                logger.info("========== 通知发送完成 ==========")
                return True
            else:
                logger.warning("[通知策略] 企业微信通知失败，准备降级使用邮件通知...")
        else:
            logger.info("[通知策略] 企业微信未启用或配置不完整，直接使用邮件通知")

        # 2. 企业微信失败或未启用时，降级使用邮件通知
        email_success = False
        if self.email_config.get("enabled", True):
            logger.info("[通知策略] 尝试使用邮件发送通知...")
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="email")
            email_success = self._send_email_alert(
                symbol, current_price, message)

            if email_success:
                logger.info("[通知结果] 邮件通知发送成功")
            else:
                logger.error("[通知结果] 邮件通知发送失败")
        else:
            logger.warning("[通知策略] 邮件通知未启用")

        # 3. 记录最终结果
        final_success = wechat_success or email_success
        if final_success:
            logger.info("========== 通知发送完成 (成功) ==========")
        else:
            logger.error("========== 通知发送完成 (全部失败) ==========")

        return final_success

    def _send_email_alert(self, symbol: str, current_price: float, message: str) -> bool:
        """发送邮件通知"""
        try:
            symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)
            subject = f"黄金价格监控报警 - {symbol_name} - {current_price}"
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['receiver_email']

            server = smtplib.SMTP(
                self.email_config['smtp_server'],
                self.email_config['smtp_port']
            )
            server.starttls()
            server.login(
                self.email_config['sender_email'],
                self.email_config['sender_password']
            )
            server.send_message(msg)
            server.quit()

            logger.info(f"[{datetime.now()}] 邮件发送成功")
            return True
        except Exception as e:
            logger.error(f"[{datetime.now()}] 邮件发送失败：{e}")
            return False

    def _send_wechat_work_alert(self, message: str) -> bool:
        """发送企业微信机器人消息"""
        if not self.wechat_config.get("webhook_url"):
            logger.warning("企业微信 webhook_url 未配置")
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
                logger.error(
                    f"[{datetime.now()}] 企业微信消息发送失败: "
                    f"status_code={response.status_code}, response={response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"[{datetime.now()}] 企业微信发送异常：{e}")
            return False

    def _send_wechat_work_markdown(self, message: str) -> bool:
        """发送企业微信 markdown 格式消息"""
        if not self.wechat_config.get("webhook_url"):
            logger.warning("企业微信 webhook_url 未配置")
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

            success = response.status_code == 200 and response.json().get("errcode") == 0
            if success:
                logger.info(f"[{datetime.now()}] 企业微信 markdown 消息发送成功")
            else:
                logger.error(
                    f"[{datetime.now()}] 企业微信 markdown 消息发送失败：{response.text}"
                )
            return success
        except Exception as e:
            logger.error(f"[{datetime.now()}] 企业微信 markdown 发送异常：{e}")
            return False
