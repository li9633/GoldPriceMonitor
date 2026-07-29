<template>
  <el-row :gutter="16" class="chart-row">
    <el-col :span="12">
      <el-card shadow="hover">
        <template #header>
          <span class="card-title">
            <font-awesome-icon icon="circle-exclamation" /> 失败原因 TOP5
          </span>
        </template>
        <div v-if="topFailures.length === 0" class="empty-chart">
          <el-empty description="暂无失败" :image-size="60" />
        </div>
        <div v-else ref="reasonsChartRef" class="chart-container"></div>
      </el-card>
    </el-col>
    <el-col :span="12">
      <el-card shadow="hover">
        <template #header>
          <span class="card-title"> <font-awesome-icon icon="chart-bar" /> 各供应商失败次数 </span>
        </template>
        <div v-if="providerFailures.length === 0" class="empty-chart">
          <el-empty description="暂无失败" :image-size="60" />
        </div>
        <div v-else ref="providerChartRef" class="chart-container"></div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faCircleExclamation, faChartBar } from '@fortawesome/free-solid-svg-icons'
import { axisColor, splitColor } from '@/utils/aiStatsHelpers'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
library.add(faCircleExclamation, faChartBar)

const props = defineProps<{
  topFailures: { reason: string; count: number }[]
  providerFailures: { provider: string; count: number }[]
}>()

const reasonsChartRef = ref<HTMLDivElement>()
const providerChartRef = ref<HTMLDivElement>()
let reasonsChart: echarts.ECharts | null = null
let providerChart: echarts.ECharts | null = null

function renderCharts() {
  if (reasonsChart && props.topFailures.length > 0) {
    reasonsChart.setOption(
      {
        grid: { top: 10, right: 20, bottom: 30, left: 50 },
        xAxis: { type: 'value', axisLabel: { color: axisColor(), fontSize: 11 } },
        yAxis: {
          type: 'category',
          data: props.topFailures.map((f) =>
            f.reason.length > 20 ? f.reason.slice(0, 20) + '...' : f.reason,
          ),
          axisLabel: { color: axisColor(), fontSize: 11 },
          inverse: true,
        },
        series: [
          {
            type: 'bar',
            data: props.topFailures.map((f) => f.count),
            itemStyle: { color: '#f56c6c', borderRadius: [0, 4, 4, 0] },
          },
        ],
        tooltip: {
          trigger: 'axis',
          formatter: (p: { name: string; value: number }[]) => {
            if (!p[0]) return ''
            return `${p[0].name}<br/>${p[0].value} 次`
          },
        },
      },
      true,
    )
  }

  if (providerChart && props.providerFailures.length > 0) {
    providerChart.setOption(
      {
        grid: { top: 10, right: 20, bottom: 30, left: 50 },
        xAxis: {
          type: 'category',
          data: props.providerFailures.map((f) => f.provider),
          axisLabel: { color: axisColor(), fontSize: 11 },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: axisColor(), fontSize: 11 },
          splitLine: { lineStyle: { color: splitColor() } },
        },
        series: [
          {
            type: 'bar',
            data: props.providerFailures.map((f) => f.count),
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#e6a23c' },
                { offset: 1, color: '#f3d19e' },
              ]),
              borderRadius: [4, 4, 0, 0],
            },
          },
        ],
        tooltip: { trigger: 'axis', formatter: '{b}<br/>失败 {c} 次' },
      },
      true,
    )
  }
}

onMounted(() => {
  if (reasonsChartRef.value) reasonsChart = echarts.init(reasonsChartRef.value)
  if (providerChartRef.value) providerChart = echarts.init(providerChartRef.value)
  renderCharts()
})

watch([() => props.topFailures, () => props.providerFailures], renderCharts, { deep: true })

onUnmounted(() => {
  reasonsChart?.dispose()
  providerChart?.dispose()
})
</script>

<style lang="scss" scoped>
.chart-row {
  margin-bottom: 16px;
}

.card-title {
  font-weight: 600;
}

.chart-container {
  width: 100%;
  height: 260px;
}

.empty-chart {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 260px;
}
</style>
