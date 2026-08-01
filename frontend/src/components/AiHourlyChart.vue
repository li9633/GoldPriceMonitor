<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title"> <font-awesome-icon icon="clock" /> 小时调用分布 </span>
    </template>
    <div ref="chartRef" class="chart-container"></div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faClock } from '@fortawesome/free-solid-svg-icons'
import { axisColor, splitColor, fillEmptyHours } from '@/utils/aiStatsHelpers'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
library.add(faClock)

const props = defineProps<{
  data: { hour: string; count: number }[]
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chart) return
  const counts = fillEmptyHours(props.data)
  const hours = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 30, left: 50 },
      xAxis: { type: 'category', data: hours, axisLabel: { color: axisColor(), fontSize: 11 } },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: axisColor(), fontSize: 11 },
        splitLine: { lineStyle: { color: splitColor() } },
      },
      series: [
        {
          type: 'bar',
          data: counts,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#409eff' },
              { offset: 1, color: '#79bbff' },
            ]),
            borderRadius: [4, 4, 0, 0],
          },
        },
      ],
      tooltip: { trigger: 'axis', formatter: '{b}:00 — {c} 次' },
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
