<template>
  <div ref="chartRef" class="rate-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { exchangeRateApi } from '@/api/modules/exchange-rate'
import type { ExchangeRateChartPoint } from '@/api/modules/exchange-rate'
import { formatTime, formatDate, formatDateTime } from '@/utils/format'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    hours?: number
  }>(),
  {
    hours: 24,
  },
)

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const chartData = ref<ExchangeRateChartPoint[]>([])

const fetchData = async () => {
  try {
    chartData.value = await exchangeRateApi.getChart({ hours: props.hours })
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

  const isLongRange = props.hours > 24
  const labelFn = isLongRange ? formatDate : formatTime
  const times = chartData.value.map((p) => labelFn(p.timestamp))
  const rates = chartData.value.map((p) => p.rate)
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
      scale: true,
      axisLabel: {
        color: isDark ? '#a09070' : '#8c7a5c',
        fontSize: 11,
        formatter: (v: number) => v.toFixed(6),
      },
      splitLine: { lineStyle: { color: isDark ? '#2a2a40' : '#e8e0d0' } },
    },
    series: [
      {
        type: 'line',
        data: rates,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#409eff', width: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.02)' },
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
        return `${label}<br/>${p.value.toFixed(4)}`
      },
    },
  })
}

watch(
  () => props.hours,
  () => fetchData(),
)

onMounted(initChart)
onUnmounted(() => chart?.dispose())
</script>

<style lang="scss" scoped>
.rate-chart {
  width: 100%;
  height: 320px;
}
</style>
