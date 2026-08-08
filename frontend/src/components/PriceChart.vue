<template>
  <div class="chart-wrapper">
    <div ref="chartRef" class="price-chart"></div>
    <div v-show="isEmpty" class="empty-overlay">
      <el-empty description="暂无价格数据" :image-size="60" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { priceApi } from '@/api/modules/gold'
import type { PriceChartPoint } from '@/api/modules/gold'
import { formatTime, formatDate, formatDateTime } from '@/utils/format'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    symbol: string
    hours?: number
  }>(),
  {
    hours: 24
  }
)

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const chartData = ref<PriceChartPoint[]>([])
const isEmpty = ref(false)

const fetchData = async () => {
  try {
    chartData.value = await priceApi.getChart(props.symbol, props.hours)
    isEmpty.value = chartData.value.length === 0
    await nextTick()
    updateChart()
  } catch {
    isEmpty.value = true
  }
}

const initChart = () => {
  if (!chartRef.value) return
  fetchData()
}

const updateChart = () => {
  if (!chartRef.value) return
  if (isEmpty.value) return
  if (!chart) chart = echarts.init(chartRef.value)

  chart.resize()
  const isLongRange = props.hours > 24
  const labelFn = isLongRange ? formatDate : formatTime
  const times = chartData.value.map((p) => labelFn(p.timestamp))
  const prices = chartData.value.map((p) => p.price)
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'

  chart.setOption({
    grid: { top: 20, right: 20, bottom: 30, left: 60 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: isDark ? '#a09070' : '#8c7a5c', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: isDark ? '#a09070' : '#8c7a5c', fontSize: 11 },
      splitLine: { lineStyle: { color: isDark ? '#2a2a40' : '#e8e0d0' } }
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
            { offset: 1, color: 'rgba(212, 160, 23, 0.02)' }
          ])
        }
      }
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (
        params:
          | { name: string; value: number; dataIndex: number }[]
          | { name: string; value: number; dataIndex: number }
      ) => {
        const p = Array.isArray(params) ? params[0] : params
        if (!p) return ''
        const raw = chartData.value[p.dataIndex]
        const label = isLongRange && raw ? formatDateTime(raw.timestamp) : p.name
        return `${label}<br/>¥${p.value.toFixed(2)}`
      }
    }
  })
}

watch(
  () => [props.symbol, props.hours],
  () => fetchData()
)

onMounted(initChart)
onUnmounted(() => chart?.dispose())
</script>

<style lang="scss" scoped>
.chart-wrapper {
  position: relative;
}

.price-chart {
  width: 100%;
  height: 320px;
}

.empty-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color);
}
</style>
