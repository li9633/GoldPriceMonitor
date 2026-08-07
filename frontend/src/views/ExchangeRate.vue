<template>
  <div class="exchange-rate">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-actions">
        <el-switch v-model="isAbbreviated" active-text="缩略" inactive-text="完整" size="small" />
        <el-switch
          v-model="autoRefresh"
          active-text="自动刷新"
          :active-value="true"
          :inactive-value="false"
        />
        <el-button text @click="refreshAll"> <font-awesome-icon icon="rotate" /> 刷新 </el-button>
      </div>
      <div class="header-left">
        <h1 class="page-title"><font-awesome-icon icon="dollar-sign" /> 美元汇率行情</h1>
        <p class="page-subtitle">实时追踪美元/人民币汇率，智能分析市场趋势</p>
      </div>
      <div v-if="loading" class="loading-bar"></div>
    </div>

    <!-- 汇览卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="16">
        <el-card class="rate-card" shadow="hover">
          <div class="rate-hero">
            <div class="rate-main">
              <span class="rate-label">最新汇率</span>
              <span class="rate-value">
                {{ dashboard?.latest_rate != null ? dashboard.latest_rate.toFixed(6) : '--' }}
              </span>
              <TrendBadge v-if="trend" :direction="trend.direction" />
            </div>
            <div class="rate-range">
              <span>
                最高
                {{ dashboard?.today_high != null ? dashboard.today_high.toFixed(4) : '—' }}
              </span>
              <span class="divider">|</span>
              <span>
                最低
                {{ dashboard?.today_low != null ? dashboard.today_low.toFixed(4) : '—' }}
              </span>
            </div>
            <div class="rate-meta">
              <span>历史记录：{{ dashboard?.record_count?.toLocaleString() ?? '--' }}</span>
              <span class="divider">|</span>
              <span>
                最新：{{ dashboard?.latest_time ? formatTime(dashboard.latest_time) : '暂无' }}
              </span>
              <span class="divider">|</span>
              <span>
                {{
                  dashboard?.data_freshness_seconds != null
                    ? dashboard.data_freshness_seconds + '秒前'
                    : '—'
                }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="trend-card" shadow="hover">
          <template #header>
            <span class="card-title"><font-awesome-icon icon="chart-line" /> 趋势分析</span>
          </template>
          <div class="trend-body">
            <div class="trend-item">
              <span class="trend-label">方向</span>
              <TrendBadge v-if="trend" :direction="trend.direction" />
              <span v-else class="text-muted">--</span>
            </div>
            <div class="trend-item">
              <span class="trend-label">斜率</span>
              <span class="trend-value">
                {{ trend ? (trend.slope >= 0 ? '+' : '') + trend.slope.toFixed(6) : '--' }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="4">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="最低价"
          :value="stats ? stats.min.toFixed(4) : '--'"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="最高价"
          :value="stats ? stats.max.toFixed(4) : '--'"
          highlight
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="均价"
          :value="stats ? stats.avg.toFixed(4) : '--'"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="样本数"
          :value="stats ? String(stats.count) : '--'"
        />
      </el-col>
      <el-col :span="4">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="标准差"
          :value="stats ? stats.std.toFixed(4) : '--'"
        />
      </el-col>
    </el-row>

    <!-- 走势图 -->
    <el-card class="chart-card" shadow="hover">
      <template #header>
        <div class="chart-header">
          <span class="card-title"> <font-awesome-icon icon="chart-simple" /> 汇率走势图 </span>
          <TimeRangeFilter
            v-model="timeRange"
            :options="timeRangeOptions"
            @params-change="onTimeParamsChange"
          />
        </div>
      </template>
      <ExchangeRateChart :hours="timeRangeHours" />
    </el-card>

    <!-- 最近记录 -->
    <el-card class="recent-card" shadow="hover">
      <template #header>
        <span class="card-title"><font-awesome-icon icon="list" /> 最近记录</span>
      </template>
      <el-table :data="recentRecords" stripe size="small" empty-text="暂无数据">
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column label="汇率" min-width="120">
          <template #default="{ row }">
            {{ row.rate.toFixed(4) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faDollarSign,
  faRotate,
  faChartLine,
  faChartSimple,
  faList,
} from '@fortawesome/free-solid-svg-icons'
import { exchangeRateApi } from '@/api/modules/exchange-rate'
import type {
  ExchangeRateDashboard,
  ExchangeRateStatistics,
  ExchangeRateTrend,
  ExchangeRateRecord,
} from '@/api/modules/exchange-rate'
import StatisticCard from '@/components/StatisticCard.vue'
import TrendBadge from '@/components/TrendBadge.vue'
import ExchangeRateChart from '@/components/ExchangeRateChart.vue'
import TimeRangeFilter from '@/components/TimeRangeFilter.vue'
import type { TimeRangeOption, TimeRangeParams } from '@/components/TimeRangeFilter.vue'
import { formatTime, formatDateTime } from '@/utils/format'

library.add(faDollarSign, faRotate, faChartLine, faChartSimple, faList)

const dashboard = ref<ExchangeRateDashboard | null>(null)
const stats = ref<ExchangeRateStatistics | null>(null)
const trend = ref<ExchangeRateTrend | null>(null)
const recentRecords = ref<ExchangeRateRecord[]>([])
const loading = ref(false)
const autoRefresh = ref(true)
const isAbbreviated = ref(false)

const timeRange = ref('24h')
const timeRangeHours = ref(24)

const timeRangeOptions: TimeRangeOption[] = [
  { label: '1小时', value: '1h', hours: 1 },
  { label: '6小时', value: '6h', hours: 6 },
  { label: '24小时', value: '24h', hours: 24 },
  { label: '7天', value: '7d', hours: 168 },
  { label: '30天', value: '30d', hours: 720 },
]

function onTimeParamsChange(params: TimeRangeParams) {
  timeRangeHours.value = params.hours ?? 24
}

let refreshTimer: ReturnType<typeof setInterval> | null = null

async function loadDashboard() {
  try {
    dashboard.value = await exchangeRateApi.getDashboard()
  } catch {
    // ignore
  }
}

async function loadStats() {
  try {
    stats.value = await exchangeRateApi.getStatistics({ hours: timeRangeHours.value })
  } catch {
    stats.value = null
  }
}

async function loadTrend() {
  try {
    trend.value = await exchangeRateApi.getTrend({ hours: timeRangeHours.value })
  } catch {
    trend.value = null
  }
}

async function loadRecent() {
  try {
    recentRecords.value = await exchangeRateApi.getRecent({ hours: 24, limit: 20 })
  } catch {
    recentRecords.value = []
  }
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([loadDashboard(), loadStats(), loadTrend(), loadRecent()])
  } finally {
    loading.value = false
  }
}

watch(timeRangeHours, () => {
  loadStats()
  loadTrend()
})

watch(
  autoRefresh,
  (val) => {
    if (val) {
      refreshTimer = setInterval(refreshAll, 10_000)
    } else if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  },
  { immediate: true },
)

onMounted(refreshAll)

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style lang="scss" scoped>
.exchange-rate {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  position: relative;
  margin-bottom: 28px;

  .header-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .header-left {
    text-align: center;
  }

  .page-title {
    font-size: 24px;
    color: var(--text-primary);
    margin: 0 0 6px 0;
  }

  .page-subtitle {
    font-size: 14px;
    color: var(--text-secondary);
    margin: 0;
  }

  .loading-bar {
    position: absolute;
    bottom: -4px;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--color-primary), var(--price-color));
    animation: loading-slide 1.5s ease-in-out infinite;
  }
}

@keyframes loading-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}

.stat-row {
  margin-bottom: 20px;
}

.rate-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  height: 100%;

  .rate-hero {
    .rate-main {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }

    .rate-label {
      font-size: 14px;
      color: var(--text-secondary);
    }

    .rate-value {
      font-size: 36px;
      font-weight: bold;
      color: var(--color-primary);
    }

    .rate-range {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 6px;

      .divider {
        margin: 0 8px;
        color: var(--border-color);
      }
    }

    .rate-meta {
      font-size: 13px;
      color: var(--text-secondary);

      .divider {
        margin: 0 8px;
        color: var(--border-color);
      }
    }
  }
}

.trend-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  height: 100%;

  .trend-body {
    .trend-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 0;

      &:not(:last-child) {
        border-bottom: 1px solid var(--border-color);
      }
    }

    .trend-label {
      font-size: 14px;
      color: var(--text-secondary);
    }

    .trend-value {
      font-size: 16px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .text-muted {
      color: var(--text-muted);
      font-size: 14px;
    }
  }
}

.chart-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  margin-bottom: 20px;

  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
}

.recent-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
