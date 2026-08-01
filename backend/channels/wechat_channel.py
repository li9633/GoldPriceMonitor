import time

from channels.base import (
    AlertData,
    BaseNotificationChannel,
    ChannelResult,
    classify_error,
)
from utils.http_utils import safe_post_json
from utils.logger import get_logger
from utils.message_template import MessageTemplate

logger = get_logger("WechatChannel")


class WechatWorkChannel(BaseNotificationChannel):
    @property
    def channel_type(self) -> str:
        return "wechat"

    @property
    def channel_name(self) -> str:
        return "企业微信"

    def validate_config(self, config: dict) -> bool:
        if not config.get("enabled", False):
            return False
        return bool(config.get("webhook_url", "").strip())

    def send(self, alert_data: AlertData, config: dict) -> ChannelResult:
        start = time.monotonic()
        if not self.validate_config(config):
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message="企业微信未启用或 webhook_url 未配置",
                latency_ms=(time.monotonic() - start) * 1000,
                error_type="config_missing",
                error_detail="webhook_url 未配置",
            )

        message = MessageTemplate.format_alert(
            alert_data.symbol,
            alert_data.current_price,
            alert_data.alert_messages,
            alert_data.suggestions,
            template_type="markdown",
            extra_info=alert_data.extra_info,
        )

        payload = {"msgtype": "markdown", "markdown": {"content": message}}
        response = safe_post_json(config["webhook_url"], payload, timeout=10)
        latency_ms = (time.monotonic() - start) * 1000

        if response is None:
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message="企业微信请求失败（网络错误）",
                latency_ms=latency_ms,
                error_type="network_timeout",
                error_detail="HTTP 请求返回 None",
            )

        if response.status_code == 200:
            resp_json = response.json()
            if resp_json.get("errcode") == 0:
                logger.info("企业微信 markdown 消息发送成功")
                return ChannelResult(
                    success=True,
                    channel_type=self.channel_type,
                    message="发送成功",
                    latency_ms=latency_ms,
                )
            else:
                err_detail = f"errcode={resp_json.get('errcode')}, errmsg={resp_json.get('errmsg')}"
                logger.error(f"企业微信消息发送失败：{err_detail}")
                return ChannelResult(
                    success=False,
                    channel_type=self.channel_type,
                    message=f"企业微信 API 错误：{err_detail}",
                    latency_ms=latency_ms,
                    error_type=classify_error(err_detail),
                    error_detail=err_detail,
                )
        else:
            err_detail = f"status_code={response.status_code}"
            logger.error(f"企业微信消息发送失败：{err_detail}")
            return ChannelResult(
                success=False,
                channel_type=self.channel_type,
                message=f"企业微信 HTTP 错误：{err_detail}",
                latency_ms=latency_ms,
                error_type=classify_error(err_detail),
                error_detail=err_detail,
            )
