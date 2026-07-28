<template>
  <div ref="chartRef" class="price-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import type { PriceChartPoint } from '@/api/modules/gold'
import { formatTime } from '@/utils/format'

const props = defineProps<{
  data: PriceChartPoint[]
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const initChart = () => {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  updateChart()
}

const updateChart = () => {
  if (!chart) return

  const times = props.data.map((p) => formatTime(p.timestamp))
  const prices = props.data.map((p) => p.price)
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
      formatter: (params: { name: string; value: number }[] | { name: string; value: number }) => {
        const p = Array.isArray(params) ? params[0] : params
        if (!p) return ''
        return `${p.name}<br/>¥${p.value.toFixed(2)}`
      },
    },
  })
}

watch(() => props.data, updateChart, { deep: true })

onMounted(initChart)
onUnmounted(() => chart?.dispose())
</script>

<style lang="scss" scoped>
.price-chart {
  width: 100%;
  height: 320px;
}
</style>
