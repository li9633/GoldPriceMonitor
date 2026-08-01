import uuid

from channels import AlertData, get_channel
from service.notification_stats_service import NotificationStatsService
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

logger = get_logger("NotificationService")


class NotificationService:
    def __init__(self):
        self.settings = SystemSettingsService()
        self.stats_service = NotificationStatsService()

    def send_alert(
        self,
        symbol: str,
        current_price: float,
        alert_messages: list[str],
        suggestions: list[str] | None = None,
        extra_info: dict | None = None,
        channel_filter: list[str] | None = None,
        stop_on_first_success: bool | None = None,
        alert_level: str = "warning",
    ) -> bool:
        suggestions = suggestions or []
        symbol_name = self.settings.get_symbol_name_map().get(symbol, symbol)
        alert_data = AlertData(
            symbol=symbol,
            symbol_name=symbol_name,
            current_price=current_price,
            alert_messages=alert_messages,
            suggestions=suggestions,
            extra_info=extra_info,
            alert_level=alert_level,
        )

        logger.info("========== 开始发送报警通知 ==========")
        logger.info(f"品种：{symbol_name}, 价格：{current_price}, 级别：{alert_level}")
        if extra_info:
            logger.info(f"额外信息：{extra_info}")

        if stop_on_first_success is None:
            strategy = self.settings.get_notification_strategy()
            stop_on_first_success = strategy.get("stop_on_first_success", True)

        channel_configs = self._get_channel_configs()
        if channel_filter:
            channel_configs = [
                c for c in channel_configs if c["channel_type"] in channel_filter
            ]

        if not channel_configs:
            logger.warning("[通知策略] 没有可用的通知渠道")
            return False

        channel_configs.sort(key=lambda c: c.get("priority", 100))

        chain_id = str(uuid.uuid4())
        chain_total = len(channel_configs)
        alert_summary = "; ".join(alert_messages)[:100]
        any_success = False

        for i, cfg in enumerate(channel_configs):
            channel_type = cfg["channel_type"]
            channel = get_channel(channel_type)
            if channel is None:
                logger.warning(f"[通知策略] 未知渠道类型：{channel_type}，跳过")
                self._record_log(
                    alert_level,
                    symbol,
                    symbol_name,
                    current_price,
                    alert_summary,
                    channel_type,
                    cfg.get("display_name", channel_type),
                    chain_id,
                    i,
                    chain_total,
                    False,
                    0,
                    "config_missing",
                    f"未找到渠道实现：{channel_type}",
                )
                continue

            logger.info(
                f"[通知策略] [{i + 1}/{chain_total}] 尝试渠道：{channel.channel_name}"
            )
            result = channel.send(alert_data, cfg)

            self._record_log(
                alert_level,
                symbol,
                symbol_name,
                current_price,
                alert_summary,
                channel_type,
                channel.channel_name,
                chain_id,
                i,
                chain_total,
                result.success,
                result.latency_ms,
                result.error_type,
                result.error_detail,
            )

            if result.success:
                any_success = True
                logger.info(f"[通知结果] {channel.channel_name} 发送成功")
                if stop_on_first_success:
                    logger.info(
                        "========== 通知发送完成 (stop_on_first_success) =========="
                    )
                    return True
            else:
                logger.warning(
                    f"[通知结果] {channel.channel_name} 发送失败：{result.error_detail}"
                )

        if any_success:
            logger.info("========== 通知发送完成 (部分成功) ==========")
        else:
            logger.error("========== 通知发送完成 (全部失败) ==========")
        return any_success

    def _get_channel_configs(self) -> list[dict]:
        channels = self.settings.get_notification_channels()
        configs = []
        for ch in channels:
            cfg = dict(ch["config"])
            cfg["channel_type"] = ch["channel_type"]
            cfg["display_name"] = ch["display_name"]
            cfg["enabled"] = ch["enabled"]
            cfg["priority"] = ch["priority"]
            configs.append(cfg)
        return [c for c in configs if c["enabled"]]

    def _record_log(
        self,
        alert_level: str,
        symbol: str,
        symbol_name: str,
        current_price: float,
        alert_summary: str,
        channel_type: str,
        channel_name: str,
        chain_id: str,
        chain_position: int,
        chain_total: int,
        success: bool,
        latency_ms: float,
        error_type: str,
        error_reason: str,
    ) -> None:
        try:
            self.stats_service.log_send(
                alert_level=alert_level,
                symbol=symbol,
                symbol_name=symbol_name,
                current_price=current_price,
                alert_summary=alert_summary,
                channel_type=channel_type,
                channel_name=channel_name,
                chain_id=chain_id,
                chain_position=chain_position,
                chain_total=chain_total,
                success=success,
                latency_ms=latency_ms,
                error_type=error_type,
                error_reason=error_reason,
            )
        except (OSError, ValueError, TypeError) as e:
            logger.error(f"写入通知记录失败：{e}")
