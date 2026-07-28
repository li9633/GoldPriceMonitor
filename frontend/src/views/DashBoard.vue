<template>
  <div class="dashboard">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="chart-line" /> 黄金价格监控</h1>
      <p class="page-subtitle">实时追踪黄金价格，智能分析市场趋势</p>
    </div>

    <!-- 数据库总览 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatCard label="数据库总记录" :value="String(dashboard?.total_records ?? '--')" />
      </el-col>
      <el-col :span="6">
        <StatCard label="监控品种数" :value="String(dashboard?.symbols?.length ?? '--')" />
      </el-col>
    </el-row>

    <!-- 品种卡片 -->
    <el-row :gutter="20" class="symbol-row">
      <el-col :span="12" v-for="item in dashboard?.symbols" :key="item.symbol">
        <el-card class="symbol-card" shadow="hover">
          <div class="symbol-header">
            <span class="symbol-name">{{ item.name }}</span>
            <el-tag size="small" type="info">{{ item.symbol }}</el-tag>
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
            <div class="symbol-meta">
              <span>记录数：{{ item.count.toLocaleString() }}</span>
              <span class="divider">|</span>
              <span>
                最新时间：{{ item.latest_time ? formatTime(item.latest_time) : '暂无' }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 走势图 -->
    <el-card v-if="selectedSymbol" class="chart-card" shadow="hover">
      <template #header>
        <span class="chart-title">
          <font-awesome-icon icon="chart-simple" />
          {{ selectedSymbol }} 走势图
        </span>
      </template>
      <PriceChart :symbol="selectedSymbol" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faChartLine, faChartSimple } from '@fortawesome/free-solid-svg-icons'
import { usePriceData } from '@/composables/usePriceData'
import { formatPrice } from '@/utils/format'
import StatCard from '@/components/StatCard.vue'
import TrendBadge from '@/components/TrendBadge.vue'
import PriceChart from '@/components/PriceChart.vue'

library.add(faChartLine, faChartSimple)

const { dashboard } = usePriceData()
const selectedSymbol = ref<string | null>(null)

function selectSymbol(symbol: string) {
  selectedSymbol.value = selectedSymbol.value === symbol ? null : symbol
}

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
        margin: 0 10px;
        color: var(--border-color);
      }
    }
  }
}

.chart-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;

  .chart-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }
}
</style>
