import smtplib
import time
from email.mime.text import MIMEText

from channels.base import (
    AlertData,
    BaseNotificationChannel,
    ChannelResult,
    classify_error,
)
from utils.logger import get_logger
from utils.message_template import MessageTemplate

logger = get_logger("EmailChannel")


class EmailChannel(BaseNotificationChannel):
    @property
    def channel_type(self) -> str:
        return "email"

    @property
    def channel_name(self) -> str:
        return "邮件通知"

    def validate_config(self, config: dict) -> bool:
        required = ["smtp_server", "sender_email", "sender_password", "receiver_email"]
        for field in required:
            if not config.get(field, "").strip():
                return False
        return True

    def send(self, alert_data: AlertData, config: dict) -> ChannelResult:
        start = time.monotonic()
        if not config.get("enabled", True):
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message="邮件通知未启用",
                latency_ms=(time.monotonic() - start) * 1000,
                error_type="config_missing",
                error_detail="邮件通知未启用",
            )

        if not self.validate_config(config):
            missing = [
                f
                for f in [
                    "smtp_server",
                    "sender_email",
                    "sender_password",
                    "receiver_email",
                ]
                if not config.get(f, "").strip()
            ]
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message=f"邮件配置不完整，缺少：{', '.join(missing)}",
                latency_ms=(time.monotonic() - start) * 1000,
                error_type="config_missing",
                error_detail=f"缺少配置项：{', '.join(missing)}",
            )

        message = MessageTemplate.format_alert(
            alert_data.symbol,
            alert_data.current_price,
            alert_data.alert_messages,
            alert_data.suggestions,
            template_type="email",
            extra_info=alert_data.extra_info,
        )

        subject = f"[报警] 黄金价格监控 - {alert_data.symbol_name} - {alert_data.current_price:.2f}"

        try:
            msg = MIMEText(message, "html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = config["sender_email"]
            msg["To"] = config["receiver_email"]

            with smtplib.SMTP(
                config["smtp_server"], config.get("smtp_port", 587)
            ) as server:
                server.starttls()
                server.login(config["sender_email"], config["sender_password"])
                server.send_message(msg)

            latency_ms = (time.monotonic() - start) * 1000
            logger.info("邮件发送成功")
            return ChannelResult(
                success=True,
                channel_type=self.channel_type,
                message="发送成功",
                latency_ms=latency_ms,
            )
        except (smtplib.SMTPException, OSError) as e:
            latency_ms = (time.monotonic() - start) * 1000
            err_detail = str(e)
            logger.error(f"邮件发送失败：{err_detail}")
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message=f"邮件发送失败：{err_detail}",
                latency_ms=latency_ms,
                error_type=classify_error(err_detail),
                error_detail=err_detail,
            )
