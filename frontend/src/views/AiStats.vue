<template>
  <div class="ai-stats">
    <!-- 连续失败告警横幅 -->
    <el-alert v-if="showAlert" type="error" :closable="false" show-icon class="alert-banner">
      <template #title>
        <font-awesome-icon icon="triangle-exclamation" />
        连续失败 {{ overview?.consecutive_failures }} 次！请立即检查供应商状态。
      </template>
    </el-alert>

    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="robot" /> AI 调用统计</h1>
      <div class="header-actions">
        <el-switch
          v-model="autoRefresh"
          active-text="自动刷新"
          :active-value="true"
          :inactive-value="false"
        />
        <el-button text @click="refreshOverview">
          <font-awesome-icon icon="rotate" /> 刷新
        </el-button>
      </div>
      <div v-if="loading" class="loading-bar"></div>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <StatCard label="今日调用" :value="String(overview?.today_total ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="成功率"
          :value="overview ? overview.success_rate.toFixed(1) + '%' : '--'"
        />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="平均延迟"
          :value="overview ? formatLatency(overview.avg_latency_ms) : '--'"
        />
      </el-col>
      <el-col :span="6">
        <StatCard label="缓存命中">
          <template #value>
            <span v-if="overview">
              {{ overview.cache_hit_count
              }}<span class="hit-rate"> ({{ overview.cache_hit_rate.toFixed(1) }}%)</span>
            </span>
            <span v-else>--</span>
          </template>
        </StatCard>
      </el-col>
    </el-row>

    <!-- 成功率趋势 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="24">
        <AiTrendChart
          :data="trendData"
          :days="trendDays"
          title="成功率趋势（近7天）"
          icon="chart-line"
          series-key="success_rate"
          color="#67c23a"
          y-axis-label="%"
          tooltip-label="成功率"
        />
      </el-col>
    </el-row>

    <!-- 延迟趋势 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="24">
        <AiTrendChart
          :data="trendData"
          :days="trendDays"
          title="延迟趋势（近7天）"
          icon="chart-line"
          series-key="avg_latency"
          color="#409eff"
          y-axis-label="ms"
          tooltip-label="延迟"
        />
      </el-col>
    </el-row>

    <!-- 小时分布 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="24">
        <AiHourlyChart :data="overview?.hourly_distribution ?? []" />
      </el-col>
    </el-row>

    <!-- 模型排名 + 供应商排名 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <el-card shadow="hover" class="ranking-card">
          <template #header>
            <span class="card-title"> <font-awesome-icon icon="ranking-star" /> 模型排名 </span>
          </template>
          <el-table :data="overview?.model_ranking ?? []" size="small" empty-text="暂无数据">
            <el-table-column label="供应商" prop="provider" min-width="80" />
            <el-table-column label="模型" prop="model" min-width="110" />
            <el-table-column label="调用量" prop="total" width="70" align="right" />
            <el-table-column label="成功率" width="80" align="right">
              <template #default="{ row }">
                <span :style="{ color: rateColor(row.success_rate) }">
                  {{ row.success_rate.toFixed(1) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="80" align="right">
              <template #default="{ row }">
                <span :style="{ color: latencyColor(row.avg_latency) }">
                  {{ formatLatency(row.avg_latency) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover" class="ranking-card">
          <template #header>
            <span class="card-title"> <font-awesome-icon icon="building" /> 供应商排名 </span>
          </template>
          <el-table :data="overview?.provider_ranking ?? []" size="small" empty-text="暂无数据">
            <el-table-column label="供应商" prop="provider" min-width="120" />
            <el-table-column label="调用量" prop="total" width="80" align="right" />
            <el-table-column label="成功率" width="80" align="right">
              <template #default="{ row }">
                <span :style="{ color: rateColor(row.success_rate) }">
                  {{ row.success_rate.toFixed(1) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="80" align="right">
              <template #default="{ row }">
                <span :style="{ color: latencyColor(row.avg_latency) }">
                  {{ formatLatency(row.avg_latency) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 失败分析 -->
    <AiFailureCharts
      :top-failures="overview?.top_failures ?? []"
      :provider-failures="overview?.provider_failures ?? []"
    />

    <!-- 调用日志 -->
    <AiCallLogs />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faRobot,
  faRotate,
  faTriangleExclamation,
  faChartLine,
  faRankingStar,
  faBuilding,
} from '@fortawesome/free-solid-svg-icons'
import { aiStatsApi } from '@/api/modules/ai-stats'
import type { AiStatsOverview, DailyTrendItem } from '@/api/modules/ai-stats'
import StatCard from '@/components/StatCard.vue'
import AiTrendChart from '@/components/AiTrendChart.vue'
import AiHourlyChart from '@/components/AiHourlyChart.vue'
import AiFailureCharts from '@/components/AiFailureCharts.vue'
import AiCallLogs from '@/components/AiCallLogs.vue'
import { formatLatency, rateColor, latencyColor } from '@/utils/aiStatsHelpers'

library.add(faRobot, faRotate, faTriangleExclamation, faChartLine, faRankingStar, faBuilding)

// —— State ——
const overview = ref<AiStatsOverview | null>(null)
const trendData = ref<DailyTrendItem[]>([])
const loading = ref(false)
const autoRefresh = ref(true)
const trendDays = ref(7)

const showAlert = computed(() => (overview.value?.consecutive_failures ?? 0) > 0)

let refreshTimer: ReturnType<typeof setInterval> | null = null

// —— Data fetching ——
async function refreshOverview() {
  loading.value = true
  try {
    overview.value = await aiStatsApi.getOverview()
  } catch {
    ElMessage.error('获取统计数据失败')
  } finally {
    loading.value = false
  }
}

async function fetchTrend() {
  try {
    trendData.value = await aiStatsApi.getTrend(trendDays.value)
  } catch {
    // ignore
  }
}

// —— Auto-refresh ——
watch(
  autoRefresh,
  (val) => {
    if (val) {
      refreshTimer = setInterval(refreshOverview, 30000)
    } else if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  },
  { immediate: true },
)

onMounted(async () => {
  await refreshOverview()
  await fetchTrend()
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style lang="scss" scoped>
.ai-stats {
  padding: 0;
}

.alert-banner {
  margin-bottom: 16px;
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

.hit-rate {
  font-size: 14px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.chart-row {
  margin-bottom: 16px;
}

.card-title {
  font-weight: 600;
}

.ranking-card {
  margin-bottom: 0;
}
</style>
