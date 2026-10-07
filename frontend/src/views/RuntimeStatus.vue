<template>
  <div class="runtime-status">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="gauge-high" /> 运行状态</h1>
      <div class="header-actions">
        <span v-if="status?.last_tick" class="file-info">
          最近巡检 {{ formatTime(status.last_tick.at) }}
        </span>
        <el-switch
          v-model="autoRefresh"
          active-text="自动刷新"
          :active-value="true"
          :inactive-value="false"
        />
        <el-button text @click="fetchStatus">
          <font-awesome-icon icon="rotate" /> 刷新
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="status?.status === 'stopped'"
      type="info"
      :closable="false"
      show-icon
      title="监控程序尚未启动（后端进程内未见启动记录）。启动后端服务后此处会实时更新。"
      class="status-alert"
    />
    <el-alert
      v-if="status?.last_error"
      type="error"
      :closable="false"
      show-icon
      class="status-alert"
    >
      <template #title>
        最近主循环错误（{{ formatTime(status.last_error.at) }}）：{{ status.last_error.message }}
      </template>
    </el-alert>

    <!-- 指标卡 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">运行状态</div>
          <el-tag
            :type="status?.status === 'running' ? 'success' : 'info'"
            size="large"
            class="status-tag"
          >
            {{ status?.status === 'running' ? '运行中' : '未运行' }}
          </el-tag>
        </el-card>
      </el-col>
      <el-col :span="4">
        <StatisticCard label="运行时长" :value="formatUptime(status?.uptime_seconds)" />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          label="累计巡检"
          :value="status?.check_count ?? 0"
          format="integer"
          :sub="status ? `近 1 小时 ${status.ticks_1h} 次` : undefined"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          label="累计投递"
          :value="status?.alert_count ?? 0"
          format="integer"
          sub="建议 / 复盘 / 通知"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          label="近 1 小时失败"
          :value="status?.failed_1h ?? 0"
          format="integer"
          :sub="failedHint"
          :sub-class="status?.failed_1h ? 'down' : 'stable'"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          label="平均巡检耗时"
          :value="status?.avg_latency_ms_1h ?? '—'"
          suffix=" ms"
          :sub="lastLatencyHint"
        />
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="hover" class="section-card">
          <template #header><span class="card-title">巡检耗时趋势（最近记录）</span></template>
          <div ref="chartRef" class="chart-container"></div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <span class="card-title">最近巡检记录（{{ status?.recent_ticks?.length ?? 0 }} 条）</span>
          </template>
          <el-table :data="status?.recent_ticks ?? []" size="small" max-height="420">
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatTime(row.at) }}</template>
            </el-table-column>
            <el-table-column label="结果" width="100">
              <template #default="{ row }">
                <el-tag :type="row.ok ? 'success' : 'danger'" size="small">
                  {{ row.ok ? '正常' : '异常' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ row.latency_ms.toFixed(0) }} ms</template>
            </el-table-column>
            <el-table-column label="主品种价格" width="120">
              <template #default="{ row }">
                {{ row.price != null ? `¥${row.price.toFixed(2)}` : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="投递" width="70" prop="events" />
            <el-table-column label="备注">
              <template #default="{ row }">
                <span class="detail-text">{{ row.detail || '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faGaugeHigh, faRotate } from '@fortawesome/free-solid-svg-icons'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import StatisticCard from '@/components/StatisticCard.vue'
import { runtimeStatusApi } from '@/api/modules/runtime-status'
import type { RuntimeStatus } from '@/api/modules/runtime-status'
import { axisColor, splitColor } from '@/utils/aiStatsHelpers'

library.add(faGaugeHigh, faRotate)

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const status = ref<RuntimeStatus | null>(null)
const autoRefresh = ref(true)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const failedHint = computed(() => {
  if (!status.value) return ''
  return status.value.failed_1h > 0 ? '存在失败巡检' : '全部正常'
})

const lastLatencyHint = computed(() => {
  const last = status.value?.last_tick
  return last ? `最近一次 ${last.latency_ms.toFixed(0)} ms` : '暂无巡检'
})

function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分`
  if (minutes > 0) return `${minutes} 分`
  return `${Math.floor(seconds)} 秒`
}

function formatTime(iso: string): string {
  return iso.replace('T', ' ')
}

async function fetchStatus() {
  try {
    status.value = await runtimeStatusApi.getStatus()
    renderChart()
  } catch {
    /* 忽略：轮询场景下不弹错误 */
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  const ticks = [...(status.value?.recent_ticks ?? [])].reverse() // 时间正序
  const xData = ticks.map((t) => t.at.slice(11)) // HH:MM:SS
  const yData = ticks.map((t) => t.latency_ms)
  chart.setOption({
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v} ms` },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: xData, axisLabel: { color: axisColor } },
    yAxis: {
      type: 'value',
      name: 'ms',
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitColor } },
    },
    series: [
      {
        type: 'line',
        data: yData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.12 },
      },
    ],
  })
}

watch(chartRef, async (el) => {
  if (el) {
    await nextTick()
    renderChart()
  }
})

onMounted(() => {
  fetchStatus()
  if (autoRefresh.value) {
    refreshTimer = setInterval(fetchStatus, 10_000)
  }
})

watch(autoRefresh, (enabled) => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (enabled) {
    refreshTimer = setInterval(fetchStatus, 10_000)
  }
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  chart?.dispose()
  chart = null
})
</script>

<style lang="scss" scoped>
.runtime-status {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;

    .page-title {
      font-size: 20px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 16px;

      .file-info {
        font-size: 13px;
        color: var(--text-secondary);
      }
    }
  }

  .status-alert {
    margin-bottom: 16px;
  }

  .stat-row {
    margin-bottom: 16px;

    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);

      .stat-label {
        font-size: 13px;
        color: var(--text-secondary);
        margin-bottom: 10px;
      }

      .status-tag {
        font-size: 15px;
      }
    }
  }

  .section-card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);

    .card-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .chart-container {
      height: 420px;
    }

    .detail-text {
      font-size: 12px;
      color: var(--text-secondary);
    }
  }
}
</style>
