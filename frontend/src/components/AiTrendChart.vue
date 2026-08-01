<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title"> <font-awesome-icon :icon="icon" /> {{ title }} </span>
    </template>
    <div ref="chartRef" class="chart-container"></div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faChartLine } from '@fortawesome/free-solid-svg-icons'
import type { DailyTrendItem } from '@/api/modules/ai-stats'
import {
  axisColor,
  splitColor,
  fillEmptyDates,
  fillEmptyTrendHours,
  formatLatency,
} from '@/utils/aiStatsHelpers'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
library.add(faChartLine)

const props = defineProps<{
  data: DailyTrendItem[]
  startDate: string
  endDate: string
  title: string
  icon: string
  seriesKey: 'success_rate' | 'avg_latency'
  color: string
  yAxisLabel: string
  tooltipLabel: string
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chart || !props.data.length) return
  const first = props.data[0]!
  const isHourly = first.hour !== null

  let xLabels: string[]
  let values: number[]
  let tooltipTitle: (name: string) => string

  if (isHourly) {
    const filled = fillEmptyTrendHours(props.data)
    xLabels = filled.map((d) => `${d.hour}:00`)
    values = filled.map((d) => d[props.seriesKey] as number)
    tooltipTitle = (name: string) => `${first.date} ${name}`
  } else {
    const filled = fillEmptyDates(props.data, props.startDate, props.endDate)
    xLabels = filled.map((d) => d.date.slice(5))
    values = filled.map((d) => d[props.seriesKey] as number)
    tooltipTitle = (name: string) => name
  }

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 30, left: 50 },
      xAxis: { type: 'category', data: xLabels, axisLabel: { color: axisColor(), fontSize: 11 } },
      yAxis: {
        type: 'value',
        axisLabel: { color: axisColor(), fontSize: 11, formatter: `{value}${props.yAxisLabel}` },
        splitLine: { lineStyle: { color: splitColor() } },
        ...(props.seriesKey === 'success_rate' ? { min: 0, max: 100 } : { scale: true }),
      },
      series: [
        {
          type: 'line',
          data: values,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: props.color, width: 2 },
          itemStyle: { color: props.color },
        },
      ],
      tooltip: {
        trigger: 'axis',
        formatter: (params: { name: string; value: number }[]) => {
          const p = params[0]
          if (!p) return ''
          const display =
            props.seriesKey === 'avg_latency' ? formatLatency(p.value) : `${p.value.toFixed(1)}%`
          return `${tooltipTitle(p.name)}<br/>${props.tooltipLabel}：${display}`
        },
      },
    },
    true,
  )
}

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value)
    renderChart()
  }
})

watch(() => props.data, renderChart, { deep: true })

onUnmounted(() => {
  chart?.dispose()
})
</script>

<style lang="scss" scoped>
.card-title {
  font-weight: 600;
}

.chart-container {
  width: 100%;
  height: 260px;
}
</style>
