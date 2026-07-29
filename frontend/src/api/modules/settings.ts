import request from '@/api/request'

export interface AlertConfig {
  enable_absolute_alert: boolean
  absolute_low_price: number
  enable_relative_alert: boolean
  relative_window_hours: number
  enable_breakout_alert: boolean
  consolidation_hours: number
  volatility_threshold: number
  enable_trend_alert: boolean
  enable_volatility_alert: boolean
  enable_ma_cross_alert: boolean
  ma_short_period: number
  ma_long_period: number
  enable_consecutive_alert: boolean
  consecutive_count: number
  enable_rapid_change_alert: boolean
  rapid_change_threshold: number
  rapid_change_window_minutes: number
  enable_long_term_low_alert: boolean
}

export interface AIConfig {
  enabled: boolean
  prompt_check: boolean
  temperature: number
  max_tokens: number
  check_interval_checks: number
  max_retries: number
  retry_base_delay: number
  cache_ttl_minutes: number
}

export interface WeChatConfig {
  enabled: boolean
  webhook_url: string
}

export interface EmailConfig {
  enabled: boolean
  smtp_server: string
  smtp_port: number
  sender_email: string
  sender_password: string
  receiver_email: string
}

export interface MonitorConfig {
  check_interval: number
  auto_import_on_start: boolean
  min_records_threshold: number
  periods: string[]
  main_symbol: string
  monitor_symbols: string[]
  trading_hours: string[][]
  ounce_to_gram: number
}

export interface MessageConfig {
  include_time: boolean
  price_format: string
  max_conditions: number
  enable_suggestions: boolean
  suggestion_level: string
  include_stop_loss: boolean
}

export interface ExchangeRate {
  rate: number | null
  updated_at: string | null
}

export interface SymbolMapping {
  symbol: string
  display_name: string
  sort_order: number
}

export interface LogConfig {
  max_bytes: number
  backup_count: number
  compress_backup: boolean
  console_output: boolean
  keep_days: number
  log_level: string
}

export interface InfrastructureConfig {
  gold_price_api_url: string
  usd_to_cny_api_url: string
  timezone: string
  log_dir: string
}

export const settingsApi = {
  getAlert() {
    return request.get<AlertConfig>('/settings/alert')
  },
  updateAlert(data: AlertConfig) {
    return request.put<AlertConfig>('/settings/alert', data)
  },

  getAI() {
    return request.get<AIConfig>('/settings/ai')
  },
  updateAI(data: AIConfig) {
    return request.put<AIConfig>('/settings/ai', data)
  },

  getWeChat() {
    return request.get<WeChatConfig>('/settings/wechat')
  },
  updateWeChat(data: WeChatConfig) {
    return request.put<WeChatConfig>('/settings/wechat', data)
  },

  getEmail() {
    return request.get<EmailConfig>('/settings/email')
  },
  updateEmail(data: EmailConfig) {
    return request.put<EmailConfig>('/settings/email', data)
  },

  getMonitor() {
    return request.get<MonitorConfig>('/settings/monitor')
  },
  updateMonitor(data: MonitorConfig) {
    return request.put<MonitorConfig>('/settings/monitor', data)
  },

  getMessage() {
    return request.get<MessageConfig>('/settings/message')
  },
  updateMessage(data: MessageConfig) {
    return request.put<MessageConfig>('/settings/message', data)
  },

  getExchangeRate() {
    return request.get<ExchangeRate>('/settings/exchange-rate')
  },
  updateExchangeRate(rate: number) {
    return request.put<string>(`/settings/exchange-rate/${rate}`)
  },

  getSymbols() {
    return request.get<SymbolMapping[]>('/settings/symbols')
  },
  updateSymbol(symbol: string, data: SymbolMapping) {
    return request.put<SymbolMapping>(`/settings/symbols/${symbol}`, data)
  },
  deleteSymbol(symbol: string) {
    return request.delete<Record<string, never>>(`/settings/symbols/${symbol}`)
  },

  getLog() {
    return request.get<LogConfig>('/settings/log')
  },
  updateLog(data: LogConfig) {
    return request.put<LogConfig>('/settings/log', data)
  },

  getInfrastructure() {
    return request.get<InfrastructureConfig>('/settings/infrastructure')
  },

  reload() {
    return request.post<Record<string, never>>('/settings/reload')
  },
}
