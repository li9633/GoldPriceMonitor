<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title">失败原因 TOP5</span>
    </template>
    <div class="chart-wrapper">
      <div ref="chartRef" class="chart-container"></div>
      <div v-show="!data.length" class="empty-overlay">
        <el-empty description="暂无失败记录" :image-size="60" />
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { FailureReasonItem } from '@/api/modules/notification'
import { axisColor } from '@/utils/aiStatsHelpers'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ data: FailureReasonItem[] }>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  if (!props.data.length) return
  chart.resize()

  chart.setOption(
    {
      grid: { top: 10, right: 20, bottom: 30, left: 50 },
      xAxis: { type: 'value', scale: true, axisLabel: { color: axisColor(), fontSize: 11 } },
      yAxis: {
        type: 'category',
        data: props.data.map((f) => f.error_type_label).reverse(),
        axisLabel: { color: axisColor(), fontSize: 11 },
        inverse: true
      },
      series: [
        {
          type: 'bar',
          data: props.data.map((f) => f.fail_count).reverse(),
          itemStyle: { color: '#f56c6c', borderRadius: [0, 4, 4, 0] }
        }
      ],
      tooltip: {
        trigger: 'axis',
        formatter: (p: { name: string; value: number }[]) => {
          if (!p[0]) return ''
          return `${p[0].name}<br/>${p[0].value} 次`
        }
      }
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

.chart-wrapper {
  position: relative;
}

.chart-container {
  width: 100%;
  height: 260px;
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
