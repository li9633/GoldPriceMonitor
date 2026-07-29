import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from config import CHINA_TZ
from service.system_settings_service import SystemSettingsService
from utils.http_utils import safe_post_json
from utils.logger import get_logger
from utils.message_template import MessageTemplate

logger = get_logger("NotificationService")


class NotificationService:
    def __init__(self):
        self.settings = SystemSettingsService()

    def send_alert(
        self,
        symbol: str,
        current_price: float,
        alert_messages: list[str],
        suggestions: list[str] | None = None,
        extra_info: dict | None = None,
    ) -> bool:
        suggestions = suggestions or []
        symbol_name = self.settings.get_symbol_name_map().get(symbol, symbol)
        wechat_config = self.settings.get_wechat_config()
        email_config = self.settings.get_email_config()

        logger.info("========== 开始发送报警通知 ==========")
        logger.info(f"品种：{symbol_name}, 价格：{current_price}")
        if extra_info:
            logger.info(f"额外信息：{extra_info}")

        wechat_success = False
        if wechat_config.get("enabled", False) and wechat_config.get("webhook_url"):
            logger.info("[通知策略] 尝试使用企业微信发送通知...")
            message = MessageTemplate.format_alert(
                symbol,
                current_price,
                alert_messages,
                suggestions,
                template_type="markdown",
                extra_info=extra_info,
            )
            wechat_success = self._send_wechat_work_markdown(message, wechat_config)
            if wechat_success:
                logger.info("[通知结果] 企业微信通知成功")
                logger.info("========== 通知发送完成 ==========")
                return True
            else:
                logger.warning("[通知策略] 企业微信通知失败，准备降级使用邮件通知...")
        else:
            logger.info("[通知策略] 企业微信未启用或配置不完整，直接使用邮件通知")

        email_success = False
        if email_config.get("enabled", True):
            logger.info("[通知策略] 尝试使用邮件发送通知...")
            message = MessageTemplate.format_alert(
                symbol,
                current_price,
                alert_messages,
                suggestions,
                template_type="email",
                extra_info=extra_info,
            )
            email_success = self._send_email_alert(
                symbol, current_price, message, email_config
            )
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

    def _send_email_alert(
        self, symbol: str, current_price: float, message: str, email_config: dict
    ) -> bool:
        try:
            symbol_name = self.settings.get_symbol_name_map().get(symbol, symbol)
            subject = f"[报警] 黄金价格监控 - {symbol_name} - {current_price:.2f}"
            msg = MIMEText(message, "html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = email_config["sender_email"]
            msg["To"] = email_config["receiver_email"]
            server = smtplib.SMTP(
                email_config["smtp_server"], email_config["smtp_port"]
            )
            server.starttls()
            server.login(email_config["sender_email"], email_config["sender_password"])
            server.send_message(msg)
            server.quit()
            logger.info(f"[{datetime.now(CHINA_TZ)}] 邮件发送成功")
            return True
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f"[{datetime.now(CHINA_TZ)}] 邮件发送失败：{e}")
            return False

    def _send_wechat_work_markdown(self, message: str, wechat_config: dict) -> bool:
        if not wechat_config.get("webhook_url"):
            logger.warning("企业微信 webhook_url 未配置")
            return False
        payload = {"msgtype": "markdown", "markdown": {"content": message}}
        response = safe_post_json(wechat_config["webhook_url"], payload, timeout=10)
        if response is None:
            return False
        if response.status_code == 200:
            resp_json = response.json()
            if resp_json.get("errcode") == 0:
                logger.info(
                    f"[{datetime.now(CHINA_TZ)}] 企业微信 markdown 消息发送成功"
                )
                return True
            else:
                logger.error(
                    f"[{datetime.now(CHINA_TZ)}] 企业微信消息发送失败：errcode={resp_json.get('errcode')}, errmsg={resp_json.get('errmsg')}"
                )
                return False
        else:
            logger.error(
                f"[{datetime.now(CHINA_TZ)}] 企业微信消息发送失败：status_code={response.status_code}"
            )
            return False
