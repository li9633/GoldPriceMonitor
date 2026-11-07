from channels.base import (
    ADVICE_KINDS,
    KIND_ADVICE,
    KIND_DIGEST,
    KIND_REOPEN_GAP,
    KIND_REVIEW,
    KIND_VOLATILITY,
    AdviceData,
    AdvicePayload,
    BaseNotificationChannel,
    ChannelResult,
    NotificationData,
    classify_error,
)
from channels.email_channel import EmailChannel
from channels.wechat_channel import WechatWorkChannel

_registry: dict[str, BaseNotificationChannel] = {}


def _init_registry() -> None:
    if _registry:
        return
    for cls in BaseNotificationChannel.__subclasses__():
        instance = cls()
        _registry[instance.channel_type] = instance


def get_channel(channel_type: str) -> BaseNotificationChannel | None:
    _init_registry()
    return _registry.get(channel_type)


def get_all_channels() -> dict[str, BaseNotificationChannel]:
    _init_registry()
    return dict(_registry)


__all__ = [
    "ADVICE_KINDS",
    "AdviceData",
    "AdvicePayload",
    "BaseNotificationChannel",
    "ChannelResult",
    "KIND_ADVICE",
    "KIND_DIGEST",
    "KIND_REOPEN_GAP",
    "KIND_REVIEW",
    "KIND_VOLATILITY",
    "EmailChannel",
    "NotificationData",
    "WechatWorkChannel",
    "classify_error",
    "get_all_channels",
    "get_channel",
]
