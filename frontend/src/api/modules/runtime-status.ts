import request from '@/api/request'

export interface TickRecord {
  /** ISO 时间（北京时间） */
  at: string
  latency_ms: number
  ok: boolean
  /** 失败/异常原因（ok=false 时有值） */
  detail: string
  price: number | null
  /** 本轮成功投递的事件数 */
  events: number
}

export interface RuntimeStatus {
  status: 'running' | 'stopped'
  started_at: string | null
  uptime_seconds: number | null
  check_count: number
  alert_count: number
  last_tick: TickRecord | null
  /** 最近 1 小时巡检次数 */
  ticks_1h: number
  /** 最近 1 小时失败次数 */
  failed_1h: number
  avg_latency_ms_1h: number | null
  last_error: { at: string; message: string } | null
  /** 最近巡检记录（最新在前，最多 50 条） */
  recent_ticks: TickRecord[]
}

export const runtimeStatusApi = {
  getStatus() {
    return request.get<RuntimeStatus>('/runtime-status')
  },
}
