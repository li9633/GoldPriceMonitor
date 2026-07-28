<template>
  <div class="price-history">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="history" /> 价格历史</h1>
    </div>

    <el-card class="chart-card">
      <template #header>
        <div class="chart-header">
          <span>价格走势</span>
          <el-radio-group v-model="timeRange" @change="loadChart">
            <el-radio-button :value="1">1小时</el-radio-button>
            <el-radio-button :value="6">6小时</el-radio-button>
            <el-radio-button :value="24">24小时</el-radio-button>
            <el-radio-button :value="168">7天</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <PriceChart :data="chartData" />
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
import { ref, onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faHistory } from '@fortawesome/free-solid-svg-icons'
import { priceApi } from '@/api/modules/gold'
import type { PriceChartPoint, PriceRecord } from '@/api/modules/gold'
import { formatPrice, formatDateTime } from '@/utils/format'
import PriceChart from '@/components/PriceChart.vue'

library.add(faHistory)

const timeRange = ref(24)
const chartData = ref<PriceChartPoint[]>([])
const recentRecords = ref<PriceRecord[]>([])

const loadChart = async () => {
  chartData.value = await priceApi.getChart('gds_AUTD', timeRange.value)
}

const loadRecent = async () => {
  recentRecords.value = await priceApi.getRecent('gds_AUTD', 20)
}

onMounted(() => {
  loadChart()
  loadRecent()
})
</script>

<style lang="scss" scoped>
.price-history {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }
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
