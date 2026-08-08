<template>
  <el-card shadow="hover">
    <template #header>
      <div class="card-header-row">
        <span class="card-title">每日趋势</span>
        <el-radio-group
          :model-value="days"
          size="small"
          @update:model-value="$emit('update:days', Number($event))"
        >
          <el-radio-button :value="7">7天</el-radio-button>
          <el-radio-button :value="30">30天</el-radio-button>
          <el-radio-button :value="90">90天</el-radio-button>
        </el-radio-group>
      </div>
    </template>
    <div class="chart-wrapper">
      <div ref="chartRef" class="chart-container chart-tall"></div>
      <div v-show="!data.length" class="empty-overlay">
        <el-empty description="暂无通知数据" :image-size="60" />
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DailyTrendItem } from '@/api/modules/notification'
import { axisColor, splitColor } from '@/utils/aiStatsHelpers'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ data: DailyTrendItem[]; days: number }>()
defineEmits<{ 'update:days': [value: number] }>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  if (!props.data.length) return

  // 填充缺失日期chart.resize()

  // 填充缺失日期，保证 X 轴连续
  const filled: DailyTrendItem[] = []
  for (let i = props.days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().slice(0, 10)
    const found = props.data.find((item) => item.date === dateStr)
    filled.push(found || { date: dateStr, total: 0, success_count: 0, fail_count: 0 })
  }

  const dates = filled.map((d) => d.date.slice(5))
  const successVals = filled.map((d) => d.success_count)
  const failVals = filled.map((d) => d.fail_count)

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 40, left: 50 },
      legend: {
        data: ['成功', '失败'],
        bottom: 0,
        textStyle: { color: axisColor(), fontSize: 11 }
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: axisColor(), fontSize: 11 }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: axisColor(), fontSize: 11 },
        splitLine: { lineStyle: { color: splitColor() } }
      },
      series: [
        {
          name: '成功',
          type: 'line',
          data: successVals,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#67c23a', width: 2 },
          itemStyle: { color: '#67c23a' }
        },
        {
          name: '失败',
          type: 'line',
          data: failVals,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#f56c6c', width: 2 },
          itemStyle: { color: '#f56c6c' }
        }
      ],
      tooltip: { trigger: 'axis' }
    },
    true
  )
}

onMounted(render)
watch(() => props.data, render, { deep: true, flush: 'post' })
onUnmounted(() => chart?.dispose())
</script>

<style lang="scss" scoped>
.card-title {
  font-weight: 600;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chart-wrapper {
  position: relative;
}

.chart-container {
  width: 100%;
}

.chart-tall {
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
