<template>
  <div class="dashboard">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="chart-line" /> 黄金价格监控</h1>
      <p class="page-subtitle">实时追踪黄金价格，智能分析市场趋势</p>
    </div>

    <!-- 数据库总览 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatCard label="数据库总记录" :value="String(dashboard?.price.total_records ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="今日新增"
          :value="String(dashboard?.price.new_records ?? '--')"
          highlight
        />
      </el-col>
      <el-col :span="6">
        <StatCard label="监控品种数" :value="String(dashboard?.active_symbols_count ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard label="主监控品种" :value="dashboard?.main_symbol ?? '--'" />
      </el-col>
    </el-row>

    <!-- AI 统计 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="4">
        <StatCard label="AI 总调用" :value="String(dashboard?.ai.total_calls ?? '--')" />
      </el-col>
      <el-col :span="4">
        <StatCard label="AI 成功" :value="String(dashboard?.ai.success_count ?? '--')" />
      </el-col>
      <el-col :span="4">
        <StatCard label="AI 失败" :value="String(dashboard?.ai.failure_count ?? '--')" />
      </el-col>
      <el-col :span="4">
        <StatCard
          label="AI 成功率"
          :value="
            dashboard?.ai.success_rate != null ? dashboard.ai.success_rate.toFixed(1) + '%' : '--'
          "
        />
      </el-col>
      <el-col :span="4">
        <StatCard label="缓存命中" :value="String(dashboard?.ai.cache_hit_count ?? '--')" />
      </el-col>
      <el-col :span="4">
        <StatCard
          label="Token 消耗"
          :value="
            dashboard?.ai.total_tokens != null ? dashboard.ai.total_tokens.toLocaleString() : '--'
          "
        />
      </el-col>
    </el-row>

    <!-- 通知统计 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatCard label="通知发送" :value="String(dashboard?.notification.total_sends ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard label="通知成功" :value="String(dashboard?.notification.success_count ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard label="通知失败" :value="String(dashboard?.notification.failure_count ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="通知成功率"
          :value="
            dashboard?.notification.success_rate != null
              ? dashboard.notification.success_rate.toFixed(1) + '%'
              : '--'
          "
        />
      </el-col>
    </el-row>

    <!-- 品种卡片 -->
    <el-row :gutter="20" class="symbol-row">
      <el-col :span="12" v-for="item in dashboard?.price.symbols" :key="item.symbol">
        <el-card class="symbol-card" shadow="hover">
          <div class="symbol-header">
            <span class="symbol-name">{{ item.name }}</span>
            <el-tag size="small" :type="themeStore.current === 'dark' ? 'primary' : 'info'">{{
              item.symbol
            }}</el-tag>
            <el-tag
              size="small"
              :type="selectedSymbol === item.symbol ? 'primary' : 'info'"
              effect="plain"
              class="chart-tag"
              @click="selectSymbol(item.symbol)"
            >
              <font-awesome-icon icon="chart-simple" /> 走势
            </el-tag>
          </div>
          <div class="symbol-body">
            <div class="symbol-price">
              <span class="price-value">
                {{ item.latest_price ? formatPrice(item.latest_price) : '暂无数据' }}
              </span>
              <TrendBadge
                v-if="item.latest_price"
                :direction="item.latest_price >= (item.latest_price ?? 0) ? 'stable' : 'stable'"
              />
            </div>
            <div class="symbol-range">
              <span>最高 {{ item.today_high != null ? formatPrice(item.today_high) : '—' }}</span>
              <span class="divider">|</span>
              <span>最低 {{ item.today_low != null ? formatPrice(item.today_low) : '—' }}</span>
            </div>
            <div class="symbol-meta">
              <span>记录数：{{ item.count.toLocaleString() }}</span>
              <span class="divider">|</span>
              <span> 最新：{{ item.latest_time ? formatTime(item.latest_time) : '暂无' }} </span>
              <span class="divider">|</span>
              <span>
                {{
                  item.data_freshness_seconds != null ? item.data_freshness_seconds + '秒前' : '—'
                }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 走势统计 -->
    <el-row v-if="selectedSymbol && stats" :gutter="20" class="stat-row">
      <el-col :span="4">
        <StatCard label="最低价" :value="formatPrice(stats.min)" />
      </el-col>
      <el-col :span="4">
        <StatCard label="最高价" :value="formatPrice(stats.max)" highlight />
      </el-col>
      <el-col :span="4">
        <StatCard label="均价" :value="formatPrice(stats.avg)" />
      </el-col>
      <el-col :span="4">
        <StatCard label="样本数" :value="String(stats.count)" />
      </el-col>
      <el-col :span="4">
        <StatCard label="标准差" :value="stats.std.toFixed(2)" />
      </el-col>
    </el-row>

    <!-- 走势图 -->
    <el-card v-if="selectedSymbol" class="chart-card" shadow="hover">
      <template #header>
        <div class="chart-header">
          <span class="chart-title">
            <font-awesome-icon icon="chart-simple" />
            {{ selectedSymbol }} 走势图
          </span>
          <TimeRangeFilter
            v-model="timeRange"
            :options="timeRangeOptions"
            @params-change="onTimeParamsChange"
          />
        </div>
      </template>
      <PriceChart :symbol="selectedSymbol" :hours="timeRange" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, defineAsyncComponent } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faChartLine, faChartSimple } from '@fortawesome/free-solid-svg-icons'
import { useThemeStore } from '@/stores/theme'
import { usePriceData } from '@/composables/usePriceData'
import { priceApi } from '@/api/modules/gold'
import type { PriceStatistics } from '@/api/modules/gold'
import { formatPrice } from '@/utils/format'
import StatCard from '@/components/StatCard.vue'
import TrendBadge from '@/components/TrendBadge.vue'
import TimeRangeFilter from '@/components/TimeRangeFilter.vue'
import type { TimeRangeOption, TimeRangeParams } from '@/components/TimeRangeFilter.vue'
const PriceChart = defineAsyncComponent(() => import('@/components/PriceChart.vue'))

library.add(faChartLine, faChartSimple)

const themeStore = useThemeStore()
const { dashboard } = usePriceData()

const timeRangeOptions: TimeRangeOption[] = [
  { label: '1小时', value: 1, hours: 1 },
  { label: '6小时', value: 6, hours: 6 },
  { label: '24小时', value: 24, hours: 24 },
  { label: '7天', value: 168, hours: 168 },
  { label: '30天', value: 720, hours: 720 },
]
const selectedSymbol = ref<string | null>(null)
const timeRange = ref(24)
const stats = ref<PriceStatistics | null>(null)

function onTimeParamsChange(params: TimeRangeParams) {
  // hours 模式只需要 hours，chart 已通过 timeRange 联动
  void params
}

function selectSymbol(symbol: string) {
  if (selectedSymbol.value === symbol) {
    selectedSymbol.value = null
    stats.value = null
  } else {
    selectedSymbol.value = symbol
    loadStats()
  }
}

const loadStats = async () => {
  if (!selectedSymbol.value) return
  try {
    stats.value = await priceApi.getStatistics(selectedSymbol.value, timeRange.value)
  } catch {
    stats.value = null
  }
}

watch(timeRange, () => {
  loadStats()
})

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style lang="scss" scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  text-align: center;
  margin-bottom: 28px;

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
}

.stat-row {
  margin-bottom: 20px;
}

.symbol-row {
  margin-bottom: 20px;
}

.symbol-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;

  .symbol-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;

    .symbol-name {
      font-size: 17px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .chart-tag {
      margin-left: auto;
      cursor: pointer;
    }
  }

  .symbol-body {
    .symbol-price {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;

      .price-value {
        font-size: 32px;
        font-weight: bold;
        color: var(--price-color);
      }
    }

    .symbol-meta {
      font-size: 13px;
      color: var(--text-secondary);

      .divider {
        margin: 0 8px;
        color: var(--border-color);
      }
    }

    .symbol-range {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 6px;

      .divider {
        margin: 0 8px;
        color: var(--border-color);
      }
    }
  }
}

.chart-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;

  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .chart-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }
}
</style>
