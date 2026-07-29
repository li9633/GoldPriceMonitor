from pydantic import BaseModel


class AlertConfigModel(BaseModel):
    enable_absolute_alert: bool = True
    absolute_low_price: float = 915.0
    enable_relative_alert: bool = True
    relative_window_hours: int = 24
    enable_breakout_alert: bool = True
    consolidation_hours: int = 12
    volatility_threshold: float = 0.003
    enable_trend_alert: bool = True
    enable_volatility_alert: bool = True
    enable_ma_cross_alert: bool = True
    ma_short_period: int = 12
    ma_long_period: int = 48
    enable_consecutive_alert: bool = True
    consecutive_count: int = 5
    enable_rapid_change_alert: bool = True
    rapid_change_threshold: float = 0.015
    rapid_change_window_minutes: int = 30
    enable_long_term_low_alert: bool = True


class AIConfigModel(BaseModel):
    enabled: bool = True
    prompt_check: bool = False
    temperature: float = 0.3
    max_tokens: int = 4096
    check_interval_minutes: int = 5
    max_retries: int = 2
    retry_base_delay: float = 0.5
    cache_ttl_minutes: int = 60


class WechatConfigModel(BaseModel):
    enabled: bool = True
    webhook_url: str = ""


class EmailConfigModel(BaseModel):
    enabled: bool = True
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: str = ""
    receiver_email: str = ""


class MonitorConfigModel(BaseModel):
    main_symbol: str = "gds_AUTD"
    monitor_symbols: list[str] = ["gds_AUTD", "hf_XAU"]
    trading_hours: list[list[str]] = [
        ["09:00", "11:30"],
        ["13:30", "15:30"],
        ["20:00", "23:59"],
        ["00:00", "02:30"],
    ]
    ounce_to_gram: float = 31.1035
    check_interval: int = 10
    auto_import_on_start: bool = True
    min_records_threshold: int = 100
    periods: list[str] = ["60d", "1y"]


class MessageConfigModel(BaseModel):
    include_time: bool = True
    price_format: str = "¥{:.2f}"
    max_conditions: int = 5
    enable_suggestions: bool = True
    suggestion_level: str = "medium"
    include_stop_loss: bool = True


class ExchangeRateModel(BaseModel):
    rate: float | None = None
    updated_at: str | None = None


class SymbolConfigItem(BaseModel):
    symbol: str
    display_name: str
    sort_order: int = 0


class LogConfigModel(BaseModel):
    max_bytes: int = 10485760
    backup_count: int = 5
    compress_backup: bool = True
    console_output: bool = True
    keep_days: int = 30
    log_level: str = "DEBUG"


class InfrastructureConfigModel(BaseModel):
    """基础设施配置 — 前端只读展示"""

    gold_price_api_url: str = ""
    usd_to_cny_api_url: str = ""
    timezone: str = "UTC+8"
    log_dir: str = "logs"
