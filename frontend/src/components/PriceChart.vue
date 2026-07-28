<template>
  <div ref="chartRef" class="price-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { priceApi } from '@/api/modules/gold'
import type { PriceChartPoint } from '@/api/modules/gold'
import { formatTime, formatDate, formatDateTime } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    symbol: string
    hours?: number
  }>(),
  {
    hours: 24,
  },
)

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const chartData = ref<PriceChartPoint[]>([])

const fetchData = async () => {
  try {
    chartData.value = await priceApi.getChart(props.symbol, props.hours)
    updateChart()
  } catch {
    // handled
  }
}

const initChart = () => {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  fetchData()
}

const updateChart = () => {
  if (!chart) return

  const isLongRange = props.hours >= 24
  const labelFn = isLongRange ? formatDate : formatTime
  const times = chartData.value.map((p) => labelFn(p.timestamp))
  const prices = chartData.value.map((p) => p.price)
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'

  chart.setOption({
    grid: { top: 20, right: 20, bottom: 30, left: 60 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: isDark ? '#a09070' : '#8c7a5c', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: isDark ? '#a09070' : '#8c7a5c', fontSize: 11 },
      splitLine: { lineStyle: { color: isDark ? '#2a2a40' : '#e8e0d0' } },
    },
    series: [
      {
        type: 'line',
        data: prices,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#d4a017', width: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(212, 160, 23, 0.3)' },
            { offset: 1, color: 'rgba(212, 160, 23, 0.02)' },
          ]),
        },
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (
        params:
          | { name: string; value: number; dataIndex: number }[]
          | { name: string; value: number; dataIndex: number },
      ) => {
        const p = Array.isArray(params) ? params[0] : params
        if (!p) return ''
        const raw = chartData.value[p.dataIndex]
        const label = isLongRange && raw ? formatDateTime(raw.timestamp) : p.name
        return `${label}<br/>¥${p.value.toFixed(2)}`
      },
    },
  })
}

watch(
  () => [props.symbol, props.hours],
  () => fetchData(),
)

onMounted(initChart)
onUnmounted(() => chart?.dispose())
</script>

<style lang="scss" scoped>
.price-chart {
  width: 100%;
  height: 320px;
}
</style>
