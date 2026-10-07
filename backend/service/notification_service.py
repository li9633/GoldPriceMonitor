import uuid

from channels import (
    ADVICE_KINDS,
    KIND_REVIEW,
    AdvicePayload,
    NotificationData,
    get_channel,
)
from models.advice import ACTION_ALERT_LEVEL
from service.notification_stats_service import NotificationStatsService
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger
from utils.message_template import MessageTemplate

logger = get_logger("NotificationService")


class NotificationService:
    def __init__(self):
        self.settings = SystemSettingsService()
        self.stats_service = NotificationStatsService()

    def send_advice(
        self,
        advice,
        current_price: float,
        extra_info: dict | None = None,
        channel_filter: list[str] | None = None,
        stop_on_first_success: bool | None = None,
    ) -> bool:
        """投递一条建议（或复盘建议）。

        `advice` 是 `models.advice.AdviceRecord`；持仓上下文从它冻结的 `evidence`
        里取，保证「消息里说的持仓」与「当时生成建议用的持仓」一致。
        """
        symbol_name = self.settings.get_symbol_name_map().get(advice.symbol, advice.symbol)
        position = (advice.evidence or {}).get("position") or {}
        action = advice.action.value
        level = ACTION_ALERT_LEVEL.get(action, "warning")
        kind = KIND_REVIEW if advice.review_horizon else "advice"

        data = NotificationData(
            kind=kind,
            symbol=advice.symbol,
            symbol_name=symbol_name,
            current_price=current_price,
            extra_info=extra_info,
            alert_level=level,
            advice=AdvicePayload(
                action=action,
                rationale=advice.rationale,
                target_grams=advice.target_grams,
                price_band_low=advice.price_band_low,
                price_band_high=advice.price_band_high,
                confidence=advice.confidence,
                signals=[signal.summary for signal in advice.signals],
                total_grams=position.get("total_grams"),
                avg_cost=position.get("avg_cost"),
                unrealized_pnl=position.get("unrealized_pnl"),
                unrealized_pnl_pct=position.get("unrealized_pnl_pct"),
                advice_id=advice.id,
                subject_lot_id=advice.subject_lot_id,
                review_horizon=advice.review_horizon,
            ),
        )
        label = MessageTemplate.ACTION_LABELS.get(action, action)
        return self._dispatch(
            data,
            summary=f"{label}：现价 {current_price}"[:100],
            channel_filter=channel_filter,
            stop_on_first_success=stop_on_first_success,
        )

    def send(
        self,
        data: NotificationData,
        channel_filter: list[str] | None = None,
        stop_on_first_success: bool | None = None,
    ) -> bool:
        """投递一条非建议类消息（波动提醒 / 每日摘要 / 节后缺口…）。

        消息语义由 `data.kind` 决定，字段放在 `data.fields`；
        渠道按 kind 自动选择渲染模板。
        """
        assert data.kind not in ADVICE_KINDS, "建议类消息请走 send_advice()"
        # 非 advice 类消息默认 info 级（除非调用方显式给了别的级别）
        if data.alert_level == "warning":
            data.alert_level = "info"
        summary = data.summary or MessageTemplate.kind_title(data.kind)
        return self._dispatch(
            data,
            summary=summary[:100],
            channel_filter=channel_filter,
            stop_on_first_success=stop_on_first_success,
        )

    def _dispatch(
        self,
        data: NotificationData,
        *,
        summary: str,
        channel_filter: list[str] | None = None,
        stop_on_first_success: bool | None = None,
    ) -> bool:
        """渠道扇出：按优先级依次投递，逐次记录，尊重 stop_on_first_success"""
        symbol = data.symbol
        symbol_name = data.symbol_name
        current_price = data.current_price
        alert_level = data.alert_level

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
        alert_summary = summary
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

            logger.debug(
                f"渠道尝试 chain={chain_id} channel={channel.channel_name} "
                f"position={i + 1}/{chain_total}"
            )
            result = channel.send(data, cfg)

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
                logger.info(
                    f"渠道投递成功 chain={chain_id} "
                    f"channel={channel.channel_name} latency_ms={result.latency_ms:.0f}"
                )
                if stop_on_first_success:
                    return True
            else:
                logger.warning(
                    f"渠道投递失败 chain={chain_id} channel={channel.channel_name} "
                    f"error_type={result.error_type} detail={result.error_detail}"
                )

        if any_success:
            logger.info(f"通知投递完成（部分成功） chain={chain_id} kind={data.kind}")
        else:
            logger.error(f"通知投递完成（全部失败） chain={chain_id} kind={data.kind}")
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
            logger.error(f"通知记录写入失败 error={e}", exc_info=e)
