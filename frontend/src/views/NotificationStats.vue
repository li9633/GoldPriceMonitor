<template>
  <div class="notification-stats">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="bell" /> 通知统计</h1>
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
      <div v-if="loading" class="loading-bar"></div>
    </div>

    <!-- 日期筛选栏 -->
    <TimeRangeFilter
      v-model="dateRange"
      :options="dateRangeOptions"
      @params-change="onDateParamsChange"
    />

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="今日发送"
          :value="String(overview?.today_total ?? '--')"
        />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="今日成功"
          :value="String(overview?.today_success ?? '--')"
        />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="成功率"
          :value="overview ? overview.success_rate.toFixed(1) + '%' : '--'"
        />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          v-model:abbreviated="isAbbreviated"
          label="平均延迟"
          :value="overview ? overview.avg_latency_ms.toFixed(0) + 'ms' : '--'"
        />
      </el-col>
    </el-row>

    <!-- 图表行 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <NotificationFailureChart :data="topFailures" />
      </el-col>
      <el-col :span="12">
        <NotificationChannelChart :data="channelStats" />
      </el-col>
    </el-row>

    <!-- 每日趋势 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="24">
        <NotificationTrendChart v-model:days="trendDays" :data="dailyTrend" />
      </el-col>
    </el-row>

    <!-- 发送记录 -->
    <NotificationLogTable
      :items="logs.items"
      :total="logs.total"
      :loading="logsLoading"
      @page-change="onLogPageChange"
      @page-size-change="onLogPageSizeChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faBell, faRotate } from '@fortawesome/free-solid-svg-icons'
import { notificationStatsApi } from '@/api/modules/notification'
import type {
  NotifyStatsOverview,
  FailureReasonItem,
  ChannelStatsItem,
  DailyTrendItem,
  NotifyLogItem,
  DateParams,
} from '@/api/modules/notification'
import StatisticCard from '@/components/StatisticCard.vue'
import NotificationFailureChart from '@/components/NotificationFailureChart.vue'
import NotificationChannelChart from '@/components/NotificationChannelChart.vue'
import NotificationTrendChart from '@/components/NotificationTrendChart.vue'
import NotificationLogTable from '@/components/NotificationLogTable.vue'
import TimeRangeFilter from '@/components/TimeRangeFilter.vue'
import type { TimeRangeOption, TimeRangeParams } from '@/components/TimeRangeFilter.vue'
import { today, offsetDate } from '@/utils/format'

library.add(faBell, faRotate)

const overview = ref<NotifyStatsOverview | null>(null)
const topFailures = ref<FailureReasonItem[]>([])
const channelStats = ref<ChannelStatsItem[]>([])
const dailyTrend = ref<DailyTrendItem[]>([])
const logs = ref<{ items: NotifyLogItem[]; total: number }>({ items: [], total: 0 })
const logsPage = ref(1)
const logsPageSize = ref(20)
const logsLoading = ref(false)
const loading = ref(false)
const autoRefresh = ref(true)
const isAbbreviated = ref(false)

const dateRange = ref('today')

const dateRangeOptions: TimeRangeOption[] = [
  { label: '昨天', value: 'yesterday', days: 1, endDays: 1 },
  { label: '今日', value: 'today', days: 0 },
  { label: '近7天', value: '7d', days: 7 },
  { label: '30天', value: '30d', days: 30 },
  { label: '90天', value: '90d', days: 90 },
]

const dateParams = ref<DateParams>({ start_date: today(), end_date: today() })

function onDateParamsChange(params: TimeRangeParams) {
  dateParams.value = params
  refreshAll()
}

const trendDays = ref(7)

const trendParams = computed<DateParams>(() => {
  const t = today()
  return { start_date: offsetDate(-trendDays.value), end_date: t }
})

let refreshTimer: ReturnType<typeof setInterval> | null = null

const loadOverview = async () => {
  try {
    overview.value = await notificationStatsApi.getOverview(dateParams.value)
  } catch {
    /* ignore */
  }
}

const loadTopFailures = async () => {
  try {
    topFailures.value = await notificationStatsApi.getTopFailures(dateParams.value)
  } catch {
    /* ignore */
  }
}

const loadChannelStats = async () => {
  try {
    channelStats.value = await notificationStatsApi.getByChannel(dateParams.value)
  } catch {
    /* ignore */
  }
}

const loadDailyTrend = async () => {
  try {
    dailyTrend.value = await notificationStatsApi.getDailyTrend(trendParams.value)
  } catch {
    /* ignore */
  }
}

const loadLogs = async () => {
  logsLoading.value = true
  try {
    const res = await notificationStatsApi.getLogs(
      logsPage.value,
      logsPageSize.value,
      dateParams.value,
    )
    logs.value = { items: res.items, total: res.total }
  } catch {
    /* ignore */
  } finally {
    logsLoading.value = false
  }
}

const onLogPageChange = (page: number) => {
  logsPage.value = page
  loadLogs()
}

const onLogPageSizeChange = (size: number) => {
  logsPageSize.value = size
  logsPage.value = 1
  loadLogs()
}

const refreshAll = () => {
  loading.value = true
  Promise.all([
    loadOverview(),
    loadTopFailures(),
    loadChannelStats(),
    loadDailyTrend(),
    loadLogs(),
  ]).finally(() => {
    loading.value = false
  })
}

watch(
  autoRefresh,
  (val) => {
    if (val) {
      refreshTimer = setInterval(refreshAll, 30000)
    } else if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  },
  { immediate: true },
)

watch(trendDays, () => {
  loadDailyTrend()
})

onMounted(refreshAll)

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style lang="scss" scoped>
.notification-stats {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
    color: var(--text-primary);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .loading-bar {
    position: absolute;
    bottom: -8px;
    left: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--color-primary), transparent);
    border-radius: 1px;
    animation: loading-slide 1.5s ease-in-out infinite;
  }
}

@keyframes loading-slide {
  0% {
    width: 0;
    left: 0;
  }
  50% {
    width: 40%;
    left: 30%;
  }
  100% {
    width: 0;
    left: 100%;
  }
}

.stat-row {
  margin-bottom: 16px;
}

.chart-row {
  margin-bottom: 16px;
}
</style>
