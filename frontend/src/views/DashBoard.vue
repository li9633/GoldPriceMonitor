<template>
  <div class="dashboard">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="chart-line" /> 黄金价格监控</h1>
      <p class="page-subtitle">实时追踪黄金价格，智能分析市场趋势</p>
    </div>

    <div v-if="snapshot" class="snapshot-area">
      <div class="price-main">
        <span class="current-price">{{ formatPrice(snapshot.current_price) }}</span>
        <TrendBadge v-if="snapshot.trend_6h" :direction="snapshot.trend_6h.direction" />
      </div>
      <div class="price-detail">
        <span>24h 最高 {{ formatPrice(snapshot.statistics_24h?.max ?? 0) }}</span>
        <span class="divider">|</span>
        <span>24h 最低 {{ formatPrice(snapshot.statistics_24h?.min ?? 0) }}</span>
        <span class="divider">|</span>
        <span>24h 均价 {{ formatPrice(snapshot.statistics_24h?.avg ?? 0) }}</span>
      </div>
    </div>

    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatCard label="MA5" :value="formatPrice(snapshot?.ma_5 ?? 0)" highlight />
      </el-col>
      <el-col :span="6">
        <StatCard label="MA10" :value="formatPrice(snapshot?.ma_10 ?? 0)" highlight />
      </el-col>
      <el-col :span="6">
        <StatCard label="MA20" :value="formatPrice(snapshot?.ma_20 ?? 0)" highlight />
      </el-col>
      <el-col :span="6">
        <StatCard label="波动率" :value="snapshot?.statistics_24h?.std?.toFixed(2) ?? '--'" />
      </el-col>
    </el-row>

    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatCard label="近90日最低" :value="formatPrice(snapshot?.min_3m ?? 0)" highlight />
      </el-col>
      <el-col :span="6">
        <StatCard label="近180日最低" :value="formatPrice(snapshot?.min_6m ?? 0)" highlight />
      </el-col>
      <el-col :span="6">
        <StatCard label="24h 数据量" :value="String(snapshot?.statistics_24h?.count ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard
          label="趋势"
          :value="
            snapshot?.trend_24h?.direction === 'up'
              ? '📈'
              : snapshot?.trend_24h?.direction === 'down'
                ? '📉'
                : '➡️'
          "
        />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { library } from '@fortawesome/fontawesome-svg-core'
import { faChartLine } from '@fortawesome/free-solid-svg-icons'
import { usePriceData } from '@/composables/usePriceData'
import { formatPrice } from '@/utils/format'
import StatCard from '@/components/StatCard.vue'
import TrendBadge from '@/components/TrendBadge.vue'

library.add(faChartLine)

const { snapshot } = usePriceData()
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

.snapshot-area {
  text-align: center;
  margin-bottom: 28px;
  padding: 24px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);

  .price-main {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-bottom: 10px;
  }

  .current-price {
    font-size: 42px;
    font-weight: bold;
    color: var(--price-color);
  }

  .price-detail {
    font-size: 13px;
    color: var(--text-secondary);

    .divider {
      margin: 0 12px;
      color: var(--border-color);
    }
  }
}

.stat-row {
  margin-bottom: 20px;
}
</style>
