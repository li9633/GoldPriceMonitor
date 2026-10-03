import type { AdviceAction, AdviceKind, AdviceStatus } from '@/api/modules/advice'

/** 建议动作 → 中文标签（与后端 MessageTemplate.ACTION_LABELS 保持一致） */
export const ACTION_LABELS: Record<AdviceAction, string> = {
  BUY_NOW: '可以买入',
  BUY_PARTIAL: '建议分批买入',
  WAIT: '建议观望',
  AVOID: '不建议买入',
  HOLD: '继续持有',
  ADD: '建议补仓',
  TAKE_PROFIT: '建议分批止盈',
  STOP_LOSS: '建议减仓止损'
}

/** 建议动作 → Element Plus 标签样式 */
export const ACTION_TAG_TYPES: Record<
  AdviceAction,
  'primary' | 'success' | 'warning' | 'info' | 'danger'
> = {
  BUY_NOW: 'warning',
  BUY_PARTIAL: 'warning',
  ADD: 'warning',
  TAKE_PROFIT: 'primary',
  STOP_LOSS: 'danger',
  WAIT: 'info',
  HOLD: 'info',
  AVOID: 'info'
}

export const KIND_LABELS: Record<AdviceKind, string> = {
  pre_purchase: '购买前',
  post_purchase: '购买后',
  plan_execution: '计划执行',
  review: '复盘'
}

export const STATUS_LABELS: Record<AdviceStatus, string> = {
  delivered: '已给出',
  acknowledged: '已读',
  acted: '已执行',
  expired: '已过期',
  suppressed: '未推送'
}

export const STATUS_TAG_TYPES: Record<
  AdviceStatus,
  'primary' | 'success' | 'warning' | 'info' | 'danger'
> = {
  delivered: 'warning',
  acknowledged: 'primary',
  acted: 'success',
  expired: 'info',
  suppressed: 'info'
}

/** 被抑制的原因 —— 「当时为什么没发」要能看懂 */
export const SUPPRESSED_REASON_LABELS: Record<string, string> = {
  silent: '休市静默，不推送也不调用 AI',
  duplicate: '与上一条建议相同且价格未明显变动',
  low_priority: '国际金休市，仅推送高优先级建议'
}

export interface EvidenceRow {
  label: string
  value: string
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {}

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const money = (value: unknown, suffix = ''): string => {
  const n = num(value)
  return n === null ? '—' : `¥${n.toFixed(2)}${suffix}`
}

const pct = (value: unknown): string => {
  const n = num(value)
  return n === null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

/**
 * 把建议冻结的 `evidence` 摊成可读的键值行。
 *
 * 只取真正有决策意义的数字，避免把整个快照平铺出来。
 */
export function evidenceRows(evidence: Record<string, unknown> | undefined): EvidenceRow[] {
  const root = asRecord(evidence)
  const market = asRecord(root.market)
  const position = asRecord(root.position)
  const rows: EvidenceRow[] = []

  if (market.current_price !== undefined) {
    rows.push({ label: '建议时价格', value: money(market.current_price, ' /克') })
  }
  if (market.avg_24h !== undefined) {
    rows.push({ label: '24 小时均价', value: money(market.avg_24h) })
  }
  if (market.volatility_pct !== undefined) {
    rows.push({ label: '24 小时波动率', value: `${num(market.volatility_pct)?.toFixed(2)}%` })
  }
  if (market.pct_from_3m_low !== undefined) {
    rows.push({ label: '距近 90 日低点', value: pct(market.pct_from_3m_low) })
  }
  if (market.pct_from_6m_low !== undefined) {
    rows.push({ label: '距近 180 日低点', value: pct(market.pct_from_6m_low) })
  }

  const totalGrams = num(position.total_grams)
  if (totalGrams) {
    rows.push({ label: '持仓', value: `${totalGrams} g` })
  }
  if (position.avg_cost !== undefined) {
    rows.push({ label: '成本价', value: money(position.avg_cost, ' /克') })
  }
  if (position.unrealized_pnl !== undefined) {
    rows.push({
      label: '浮动盈亏',
      value: `${money(position.unrealized_pnl)}（${pct(position.unrealized_pnl_pct)}）`
    })
  }
  const ratio = num(root.position_ratio_pct)
  if (ratio !== null) {
    rows.push({ label: '持仓占总资金', value: `${ratio.toFixed(1)}%` })
  }

  const entry = asRecord(root.entry_strategy)
  if (entry.sample_count !== undefined) {
    rows.push({ label: '建仓方式回测样本', value: `${num(entry.sample_count) ?? 0} 个` })
  }
  if (entry.recommended_tranches !== undefined) {
    const tranches = num(entry.recommended_tranches) ?? 1
    rows.push({ label: '回测建议', value: tranches > 1 ? `分 ${tranches} 批` : '一次性买入' })
  }
  if (entry.volatility_percentile !== undefined && entry.volatility_percentile !== null) {
    rows.push({
      label: '波动率历史分位',
      value: `${num(entry.volatility_percentile)?.toFixed(0)}%`
    })
  }
  return rows
}

/** 建议有效性里，"价格变动" 只是原始事实；是否算"准"取决于动作方向 */
export function reviewMoveText(action: AdviceAction, movePct: number | null): string {
  if (movePct === null) return '—'
  const text = `${movePct >= 0 ? '+' : ''}${movePct.toFixed(2)}%`
  if (action === 'BUY_NOW' || action === 'BUY_PARTIAL' || action === 'ADD') {
    return movePct <= 0 ? `${text}（买后下跌，偏不利）` : `${text}（买后上涨，偏有利）`
  }
  if (action === 'TAKE_PROFIT' || action === 'STOP_LOSS') {
    return movePct >= 0 ? `${text}（卖出后上涨，偏不利）` : `${text}（卖出后下跌，偏有利）`
  }
  return text
}
