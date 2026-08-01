from fastapi import APIRouter

from models.response import ApiResponse
from models.system_settings import (
    AIConfigModel,
    AlertConfigModel,
    EmailConfigModel,
    ExchangeRateModel,
    InfrastructureConfigModel,
    LogConfigModel,
    MessageConfigModel,
    MonitorConfigModel,
    NotificationChannelModel,
    NotificationStrategyModel,
    SymbolConfigItem,
    WechatConfigModel,
)
from service.system_settings_service import SystemSettingsService

router = APIRouter(prefix="/settings", tags=["系统设置"])
service = SystemSettingsService()


@router.get("/alert", response_model=ApiResponse[AlertConfigModel])
def get_alert_config():
    return ApiResponse.ok(AlertConfigModel(**service.get_alert_config()))


@router.put("/alert", response_model=ApiResponse[AlertConfigModel])
def update_alert_config(data: AlertConfigModel):
    service.update_alert_config(**data.model_dump())
    return ApiResponse.ok(
        AlertConfigModel(**service.get_alert_config()), message="报警配置已更新"
    )


@router.get("/ai", response_model=ApiResponse[AIConfigModel])
def get_ai_config():
    return ApiResponse.ok(AIConfigModel(**service.get_ai_config()))


@router.put("/ai", response_model=ApiResponse[AIConfigModel])
def update_ai_config(data: AIConfigModel):
    service.update_ai_config(**data.model_dump())
    return ApiResponse.ok(
        AIConfigModel(**service.get_ai_config()), message="AI 配置已更新"
    )


@router.get("/wechat", response_model=ApiResponse[WechatConfigModel])
def get_wechat_config():
    return ApiResponse.ok(WechatConfigModel(**service.get_wechat_config()))


@router.put("/wechat", response_model=ApiResponse[WechatConfigModel])
def update_wechat_config(data: WechatConfigModel):
    service.update_wechat_config(**data.model_dump())
    return ApiResponse.ok(
        WechatConfigModel(**service.get_wechat_config()), message="企业微信配置已更新"
    )


@router.get("/email", response_model=ApiResponse[EmailConfigModel])
def get_email_config():
    return ApiResponse.ok(EmailConfigModel(**service.get_email_config()))


@router.put("/email", response_model=ApiResponse[EmailConfigModel])
def update_email_config(data: EmailConfigModel):
    service.update_email_config(**data.model_dump())
    return ApiResponse.ok(
        EmailConfigModel(**service.get_email_config()), message="邮件配置已更新"
    )


@router.get("/monitor", response_model=ApiResponse[MonitorConfigModel])
def get_monitor_config():
    return ApiResponse.ok(MonitorConfigModel(**service.get_monitor_config()))


@router.put("/monitor", response_model=ApiResponse[MonitorConfigModel])
def update_monitor_config(data: MonitorConfigModel):
    service.update_monitor_config(**data.model_dump())
    return ApiResponse.ok(
        MonitorConfigModel(**service.get_monitor_config()), message="监控配置已更新"
    )


@router.get("/message", response_model=ApiResponse[MessageConfigModel])
def get_message_config():
    return ApiResponse.ok(MessageConfigModel(**service.get_message_config()))


@router.put("/message", response_model=ApiResponse[MessageConfigModel])
def update_message_config(data: MessageConfigModel):
    service.update_message_config(**data.model_dump())
    return ApiResponse.ok(
        MessageConfigModel(**service.get_message_config()), message="消息配置已更新"
    )


@router.get("/symbols", response_model=ApiResponse[list[SymbolConfigItem]])
def get_symbol_config():
    return ApiResponse.ok([SymbolConfigItem(**s) for s in service.get_symbol_config()])


@router.put("/symbols/{symbol}", response_model=ApiResponse[SymbolConfigItem])
def upsert_symbol(symbol: str, data: SymbolConfigItem):
    service.upsert_symbol(symbol, data.display_name, data.sort_order)
    updated = service.get_symbol_config()
    for s in updated:
        if s["symbol"] == symbol:
            return ApiResponse.ok(SymbolConfigItem(**s), message="品种配置已更新")
    return ApiResponse.fail("更新失败", code=500)


@router.delete("/symbols/{symbol}", response_model=ApiResponse[dict])
def delete_symbol(symbol: str):
    if service.delete_symbol(symbol):
        return ApiResponse.ok({}, message=f"品种 [{symbol}] 已删除")
    return ApiResponse.fail(f"品种 [{symbol}] 不存在", code=404)


@router.get("/log", response_model=ApiResponse[LogConfigModel])
def get_log_config():
    return ApiResponse.ok(LogConfigModel(**service.get_log_config()))


@router.put("/log", response_model=ApiResponse[LogConfigModel])
def update_log_config(data: LogConfigModel):
    service.update_log_config(**data.model_dump())
    return ApiResponse.ok(
        LogConfigModel(**service.get_log_config()), message="日志配置已更新"
    )


@router.get("/infrastructure", response_model=ApiResponse[InfrastructureConfigModel])
def get_infrastructure_config():
    return ApiResponse.ok(
        InfrastructureConfigModel(**service.get_infrastructure_config())
    )


@router.get(
    "/notification/channels",
    response_model=ApiResponse[list[NotificationChannelModel]],
)
def get_notification_channels():
    return ApiResponse.ok(
        [NotificationChannelModel(**c) for c in service.get_notification_channels()]
    )


@router.put(
    "/notification/channels/{channel_type}",
    response_model=ApiResponse[NotificationChannelModel],
)
def update_notification_channel(channel_type: str, data: NotificationChannelModel):
    service.update_notification_channel(
        channel_type, data.display_name, data.enabled, data.priority, data.config
    )
    channels = service.get_notification_channels()
    for c in channels:
        if c["channel_type"] == channel_type:
            return ApiResponse.ok(
                NotificationChannelModel(**c), message="渠道配置已更新"
            )
    return ApiResponse.fail("渠道不存在", code=404)


@router.delete(
    "/notification/channels/{channel_type}", response_model=ApiResponse[dict]
)
def delete_notification_channel(channel_type: str):
    if service.delete_notification_channel(channel_type):
        return ApiResponse.ok({}, message=f"渠道 [{channel_type}] 已删除")
    return ApiResponse.fail(f"渠道 [{channel_type}] 不存在", code=404)


@router.get(
    "/notification/strategy",
    response_model=ApiResponse[NotificationStrategyModel],
)
def get_notification_strategy():
    return ApiResponse.ok(
        NotificationStrategyModel(**service.get_notification_strategy())
    )


@router.put(
    "/notification/strategy",
    response_model=ApiResponse[NotificationStrategyModel],
)
def update_notification_strategy(data: NotificationStrategyModel):
    service.update_notification_strategy(**data.model_dump())
    return ApiResponse.ok(
        NotificationStrategyModel(**service.get_notification_strategy()),
        message="通知策略已更新",
    )


@router.get("/exchange-rate", response_model=ApiResponse[ExchangeRateModel])
def get_exchange_rate():
    row = service.mapper.get_exchange_rate()
    if row:
        return ApiResponse.ok(
            ExchangeRateModel(rate=row["rate"], updated_at=row["updated_at"])
        )
    return ApiResponse.ok(ExchangeRateModel(rate=None, updated_at=None))


@router.put("/exchange-rate/{rate}", response_model=ApiResponse[ExchangeRateModel])
def update_exchange_rate(rate: float):
    service.set_cached_exchange_rate(rate)
    row = service.mapper.get_exchange_rate()
    return ApiResponse.ok(
        ExchangeRateModel(
            rate=row["rate"] if row else None,
            updated_at=row["updated_at"] if row else None,
        ),
        message="汇率已更新",
    )
