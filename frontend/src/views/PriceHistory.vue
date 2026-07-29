<template>
  <div class="price-history">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="history" /> 价格历史</h1>
      <div class="header-right">
        <span class="symbol-label">品种</span>
        <el-select v-model="symbol" class="symbol-select" @change="onSymbolChange">
          <el-option
            v-for="s in symbols"
            :key="s.symbol"
            :label="`${s.name} (${s.symbol})`"
            :value="s.symbol"
          />
        </el-select>
      </div>
    </div>

    <el-row v-if="stats" :gutter="20" class="stat-row">
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

    <el-card class="chart-card">
      <template #header>
        <div class="chart-header">
          <span>价格走势</span>
          <el-radio-group v-model="timeRange" @change="loadChartData">
            <el-radio-button :value="1">1小时</el-radio-button>
            <el-radio-button :value="6">6小时</el-radio-button>
            <el-radio-button :value="24">24小时</el-radio-button>
            <el-radio-button :value="168">7天</el-radio-button>
            <el-radio-button :value="720">30天</el-radio-button>
            <el-radio-button :value="2160">90天</el-radio-button>
            <el-radio-button :value="8760">1年</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <PriceChart :symbol="symbol" :hours="timeRange" />
    </el-card>

    <el-card class="recent-card">
      <template #header>
        <div class="chart-header">
          <span>最近记录</span>
          <el-button text type="primary" @click="loadRecent">刷新</el-button>
        </div>
      </template>
      <el-table :data="recentRecords" stripe size="small">
        <el-table-column
          prop="timestamp"
          label="时间"
          :formatter="(r: { timestamp: string }) => formatDateTime(r.timestamp)"
        />
        <el-table-column prop="price" label="价格">
          <template #default="{ row }">{{ formatPrice(row.price) }}</template>
        </el-table-column>
        <el-table-column prop="symbol" label="品种" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, defineAsyncComponent } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faHistory } from '@fortawesome/free-solid-svg-icons'
import { priceApi } from '@/api/modules/gold'
import type { PriceRecord, PriceStatistics } from '@/api/modules/gold'
import { formatPrice, formatDateTime } from '@/utils/format'
import { usePriceData } from '@/composables/usePriceData'
const PriceChart = defineAsyncComponent(() => import('@/components/PriceChart.vue'))
import StatCard from '@/components/StatCard.vue'

library.add(faHistory)

const { dashboard } = usePriceData()

const symbols = computed(() => dashboard.value?.symbols ?? [])
const symbol = ref('gds_AUTD')
const timeRange = ref(24)
const recentRecords = ref<PriceRecord[]>([])
const stats = ref<PriceStatistics | null>(null)

const loadRecent = async () => {
  recentRecords.value = await priceApi.getRecent(symbol.value, 20)
}

const loadStats = async () => {
  try {
    stats.value = await priceApi.getStatistics(symbol.value, timeRange.value)
  } catch {
    stats.value = null
  }
}

const loadChartData = () => {
  loadStats()
}

const onSymbolChange = () => {
  loadRecent()
  loadStats()
}

watch(timeRange, () => {
  loadStats()
})

onMounted(() => {
  loadRecent()
  loadStats()
})
</script>

<style lang="scss" scoped>
.price-history {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .symbol-label {
    font-size: 14px;
    color: var(--text-secondary);
  }

  .symbol-select {
    width: 220px;
  }
}

.stat-row {
  margin-bottom: 20px;
}

.chart-card {
  margin-bottom: 20px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.recent-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
}
</style>
