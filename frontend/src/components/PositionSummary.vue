<template>
  <el-row :gutter="20" class="position-summary">
    <el-col :span="6">
      <StatisticCard label="持仓克数" :value="gramsText" format="raw" />
    </el-col>
    <el-col :span="6">
      <StatisticCard label="持仓成本价" :value="avgCostText" format="raw" />
    </el-col>
    <el-col :span="6">
      <StatisticCard label="当前市值" :value="marketValueText" format="raw" />
    </el-col>
    <el-col :span="6">
      <StatisticCard
        label="浮动盈亏"
        :value="pnlText"
        format="raw"
        :sub="pnlSubText"
        :sub-class="pnlClass"
        highlight
      />
    </el-col>
    <el-col v-if="hasSales" :span="6">
      <StatisticCard
        label="已实现盈亏"
        :value="realizedText"
        format="raw"
        :sub="realizedSubText"
        :sub-class="realizedClass"
      />
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StatisticCard from '@/components/StatisticCard.vue'
import type { PortfolioSummary } from '@/api/modules/portfolio'

const props = defineProps<{
  summary: PortfolioSummary | null
}>()

/** 拿不到行情时统一显示「暂无行情」，避免把缺失显示成 0 */
const NO_QUOTE = '暂无行情'

const gramsText = computed(() => {
  if (!props.summary) return '--'
  return `${props.summary.total_grams} g`
})

const avgCostText = computed(() => {
  const positions = props.summary?.positions ?? []
  if (!positions.length || props.summary!.total_grams <= 0) return '--'
  const avg = props.summary!.total_cost / props.summary!.total_grams
  return `¥${avg.toFixed(2)} /克`
})

const marketValueText = computed(() => {
  const value = props.summary?.total_market_value
  return value == null ? NO_QUOTE : `¥${value.toFixed(2)}`
})

const pnlText = computed(() => {
  const pnl = props.summary?.total_unrealized_pnl
  if (pnl == null) return NO_QUOTE
  const sign = pnl >= 0 ? '+' : '-'
  return `${sign}¥${Math.abs(pnl).toFixed(2)}`
})

const pnlSubText = computed(() => {
  const pct = props.summary?.total_unrealized_pnl_pct
  if (pct == null) return undefined
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
})

const pnlClass = computed<'up' | 'down' | 'stable'>(() => {
  const pnl = props.summary?.total_unrealized_pnl
  if (pnl == null) return 'stable'
  if (pnl > 0) return 'up'
  if (pnl < 0) return 'down'
  return 'stable'
})

/** 没卖过就不显示这张卡，避免用「已实现 ¥0.00」占位置 */
const hasSales = computed(() => (props.summary?.total_sold_grams ?? 0) > 0)

const realizedText = computed(() => {
  const pnl = props.summary?.total_realized_pnl ?? 0
  const sign = pnl >= 0 ? '+' : '-'
  return `${sign}¥${Math.abs(pnl).toFixed(2)}`
})

const realizedSubText = computed(() => {
  const grams = props.summary?.total_sold_grams ?? 0
  return `已卖出 ${grams} g（不含手续费）`
})

const realizedClass = computed<'up' | 'down' | 'stable'>(() => {
  const pnl = props.summary?.total_realized_pnl ?? 0
  if (pnl > 0) return 'up'
  if (pnl < 0) return 'down'
  return 'stable'
})
</script>

<style lang="scss" scoped>
.position-summary {
  margin-bottom: 20px;
}
</style>
