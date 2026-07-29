import request from '@/api/request'

export interface LogContent {
  lines: string[]
  total_lines: number
  file_size: number
  file_name: string
}

export interface LogQueryParams {
  lines?: number
  offset?: number
  level?: string
  search?: string
}

export const logsApi = {
  getContent(params?: LogQueryParams) {
    return request.get<LogContent>('/logs/content', { params })
  },
}
