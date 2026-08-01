import request from '@/api/request'

// ========== 通知渠道 ==========
export interface NotificationChannelConfig {
  webhook_url?: string
  smtp_server?: string
  smtp_port?: number
  sender_email?: string
  sender_password?: string
  receiver_email?: string
}

export interface NotificationChannelModel {
  channel_type: string
  display_name: string
  enabled: boolean
  priority: number
  config: NotificationChannelConfig
}

// ========== 通知策略 ==========
export interface NotificationStrategyModel {
  stop_on_first_success: boolean
}

// ========== 统计概览 ==========
export interface NotifyStatsOverview {
  today_total: number
  today_success: number
  today_failure: number
  success_rate: number
  avg_latency_ms: number
  total_all: number
}

// ========== 失败原因 ==========
export interface FailureReasonItem {
  error_type: string
  error_type_label: string
  fail_count: number
  percentage: number
  examples: string
}

// ========== 按渠道统计 ==========
export interface ChannelStatsItem {
  channel_type: string
  channel_name: string
  total: number
  success_count: number
  fail_count: number
  success_rate: number
  avg_latency_ms: number
}

// ========== 每日趋势 ==========
export interface DailyTrendItem {
  date: string
  total: number
  success_count: number
  fail_count: number
}

// ========== 通知日志 ==========
export interface NotifyLogItem {
  id: number
  alert_level: string
  symbol: string
  symbol_name: string
  current_price: number | null
  alert_summary: string
  channel_type: string
  channel_name: string
  chain_id: string
  chain_position: number
  chain_total: number
  success: boolean
  latency_ms: number | null
  error_type: string
  error_reason: string
  created_at: string
}

// ========== 分页响应 ==========
export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ========== 通知渠道 API ==========
export const notificationChannelApi = {
  getChannels() {
    return request.get<NotificationChannelModel[]>('/settings/notification/channels')
  },
  updateChannel(channelType: string, data: NotificationChannelModel) {
    return request.put<NotificationChannelModel>(
      `/settings/notification/channels/${channelType}`,
      data,
    )
  },
  deleteChannel(channelType: string) {
    return request.delete<Record<string, never>>(`/settings/notification/channels/${channelType}`)
  },
}

// ========== 通知策略 API ==========
export const notificationStrategyApi = {
  getStrategy() {
    return request.get<NotificationStrategyModel>('/settings/notification/strategy')
  },
  updateStrategy(data: NotificationStrategyModel) {
    return request.put<NotificationStrategyModel>('/settings/notification/strategy', data)
  },
}

export interface DateParams {
  hours?: number
  start_date?: string
  end_date?: string
}

// ========== 通知统计 API ==========
export const notificationStatsApi = {
  getOverview(params?: DateParams) {
    return request.get<NotifyStatsOverview>('/notification-stats/overview', { params })
  },
  getTopFailures(params?: DateParams) {
    return request.get<FailureReasonItem[]>('/notification-stats/top-failures', {
      params,
    })
  },
  getByChannel(params?: DateParams) {
    return request.get<ChannelStatsItem[]>('/notification-stats/by-channel', {
      params,
    })
  },
  getDailyTrend(params?: DateParams) {
    return request.get<DailyTrendItem[]>('/notification-stats/daily-trend', {
      params,
    })
  },
  getLogs(page = 1, pageSize = 20, params?: DateParams) {
    return request.get<PageResponse<NotifyLogItem>>('/notification-stats/logs', {
      params: { page, page_size: pageSize, ...params },
    })
  },
  getChain(chainId: string) {
    return request.get<NotifyLogItem[]>(`/notification-stats/chain/${chainId}`)
  },
}
