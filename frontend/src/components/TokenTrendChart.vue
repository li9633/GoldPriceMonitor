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
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faChartLine } from '@fortawesome/free-solid-svg-icons'
import type { TokenTrendItem } from '@/api/modules/ai-stats'
import { axisColor, splitColor } from '@/utils/aiStatsHelpers'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])
library.add(faChartLine)

const props = defineProps<{
  data: TokenTrendItem[]
  days: number
  title: string
  icon: string
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function formatTokenNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function renderChart() {
  if (!chart || !props.data.length) return
  const dates = props.data.map((d) => d.date.slice(5))
  const promptData = props.data.map((d) => d.prompt_tokens)
  const completionData = props.data.map((d) => d.completion_tokens)
  const totalData = props.data.map((d) => d.total_tokens)

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 30, left: 60 },
      legend: {
        data: ['输入Token', '输出Token', '总Token'],
        bottom: 0,
        textStyle: { color: axisColor(), fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: axisColor(), fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: axisColor(),
          fontSize: 11,
          formatter: (v: number) => formatTokenNum(v),
        },
        splitLine: { lineStyle: { color: splitColor() } },
      },
      series: [
        {
          name: '输入Token',
          type: 'line',
          data: promptData,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#409eff', width: 2 },
          itemStyle: { color: '#409eff' },
        },
        {
          name: '输出Token',
          type: 'line',
          data: completionData,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#67c23a', width: 2 },
          itemStyle: { color: '#67c23a' },
        },
        {
          name: '总Token',
          type: 'line',
          data: totalData,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#e6a23c', width: 2 },
          itemStyle: { color: '#e6a23c' },
        },
      ],
      tooltip: {
        trigger: 'axis',
        formatter: (params: { seriesName: string; value: number; name: string }[]) => {
          let html = params[0]?.name ?? ''
          params.forEach((p) => {
            html += `<br/>${p.seriesName}：${p.value.toLocaleString()}`
          })
          return html
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
  height: 280px;
}
</style>
