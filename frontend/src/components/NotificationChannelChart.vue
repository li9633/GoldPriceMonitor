<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title">按渠道统计</span>
    </template>
    <div ref="chartRef" class="chart-container"></div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ChannelStatsItem } from '@/api/modules/notification'
import { axisColor, splitColor } from '@/utils/aiStatsHelpers'

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ data: ChannelStatsItem[] }>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value || !props.data.length) return
  if (!chart) chart = echarts.init(chartRef.value)

  const names = props.data.map((c) => c.channel_name)
  const successData = props.data.map((c) => c.success_count)
  const failData = props.data.map((c) => c.fail_count)

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 30, left: 50 },
      legend: {
        data: ['成功', '失败'],
        bottom: 0,
        textStyle: { color: axisColor(), fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: names,
        axisLabel: { color: axisColor(), fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: axisColor(), fontSize: 11 },
        splitLine: { lineStyle: { color: splitColor() } },
      },
      series: [
        {
          name: '成功',
          type: 'bar',
          data: successData,
          stack: 'total',
          itemStyle: { color: '#67c23a', borderRadius: [4, 4, 0, 0] },
        },
        {
          name: '失败',
          type: 'bar',
          data: failData,
          stack: 'total',
          itemStyle: { color: '#f56c6c', borderRadius: [4, 4, 0, 0] },
        },
      ],
      tooltip: { trigger: 'axis' },
    },
    true,
  )
}

onMounted(render)
watch(() => props.data, render, { deep: true })
onUnmounted(() => chart?.dispose())
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
