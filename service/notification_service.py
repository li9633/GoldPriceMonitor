import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

from config import EMAIL_CONFIG, SYMBOL_NAME_MAP, WECHAT_WORK_CONFIG
from utils.http_utils import safe_post_json
from utils.logger import get_logger
from utils.message_template import MessageTemplate

logger = get_logger("NotificationService")


class NotificationService:
    def __init__(self):
        self.email_config = EMAIL_CONFIG
        self.wechat_config = WECHAT_WORK_CONFIG

    def send_alert(self, symbol: str, current_price: float,
                   alert_messages: list[str],
                   suggestions: list[str] | None = None,
                   extra_info: dict | None = None) -> bool:
        suggestions = suggestions or []
        symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)

        logger.info("========== 开始发送报警通知 ==========")
        logger.info(f"品种：{symbol_name}, 价格：{current_price}")
        if extra_info:
            logger.info(f"额外信息：{extra_info}")

        wechat_success = False
        if self.wechat_config.get("enabled", False) and self.wechat_config.get("webhook_url"):
            logger.info("[通知策略] 尝试使用企业微信发送通知...")
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="markdown",
                extra_info=extra_info)
            wechat_success = self._send_wechat_work_markdown(message)
            if wechat_success:
                logger.info("[通知结果] 企业微信通知成功")
                logger.info("========== 通知发送完成 ==========")
                return True
            else:
                logger.warning("[通知策略] 企业微信通知失败，准备降级使用邮件通知...")
        else:
            logger.info("[通知策略] 企业微信未启用或配置不完整，直接使用邮件通知")

        email_success = False
        if self.email_config.get("enabled", True):
            logger.info("[通知策略] 尝试使用邮件发送通知...")
            message = MessageTemplate.format_alert(
                symbol, current_price, alert_messages,
                suggestions, template_type="email",
                extra_info=extra_info)
            email_success = self._send_email_alert(
                symbol, current_price, message)
            if email_success:
                logger.info("[通知结果] 邮件通知发送成功")
            else:
                logger.error("[通知结果] 邮件通知发送失败")
        else:
            logger.warning("[通知策略] 邮件通知未启用")

        final_success = wechat_success or email_success
        if final_success:
            logger.info("========== 通知发送完成 (成功) ==========")
        else:
            logger.error("========== 通知发送完成 (全部失败) ==========")
        return final_success

    def _send_email_alert(self, symbol: str, current_price: float, message: str) -> bool:
        try:
            symbol_name = SYMBOL_NAME_MAP.get(symbol, symbol)
            subject = f"[报警] 黄金价格监控 - {symbol_name} - {current_price:.2f}"
            msg = MIMEText(message, 'html', 'utf-8')
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
            logger.info(f"[{datetime.now(timezone.utc)}] 邮件发送成功")
            return True
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f"[{datetime.now(timezone.utc)}] 邮件发送失败：{e}")
            return False

    def _send_wechat_work_markdown(self, message: str) -> bool:
        if not self.wechat_config.get("webhook_url"):
            logger.warning("企业微信 webhook_url 未配置")
            return False
        payload = {"msgtype": "markdown", "markdown": {"content": message}}
        response = safe_post_json(
            self.wechat_config["webhook_url"], payload, timeout=10)
        if response is None:
            return False
        if response.status_code == 200:
            resp_json = response.json()
            if resp_json.get("errcode") == 0:
                logger.info(f"[{datetime.now(timezone.utc)}] 企业微信 markdown 消息发送成功")
                return True
            else:
                logger.error(
                    f"[{datetime.now(timezone.utc)}] 企业微信消息发送失败：errcode={resp_json.get('errcode')}, errmsg={resp_json.get('errmsg')}")
                return False
        else:
            logger.error(
                f"[{datetime.now(timezone.utc)}] 企业微信消息发送失败：status_code={response.status_code}")
            return False