<template>
  <div class="advice-history">
    <div class="page-header">
      <div class="header-actions">
        <el-button text :loading="loading" @click="loadAll">
          <font-awesome-icon icon="rotate" /> 刷新
        </el-button>
        <el-button :loading="refreshing" @click="refreshReviews">
          <font-awesome-icon icon="clock-rotate-left" /> 回填回访价格
        </el-button>
      </div>
      <div class="header-left">
        <h1 class="page-title"><font-awesome-icon icon="clock-rotate-left" /> 建议历史</h1>
        <p class="page-subtitle">
          每一条都冻结了当时的行情与持仓，可回溯；T+1/T+7/T+30 用于检验建议准不准
        </p>
      </div>
    </div>

    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <StatisticCard label="建议总数" :value="String(stats?.total ?? 0)" format="raw" />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          label="T+1 平均变动"
          :value="moveText(stats?.avg_move_t1_pct)"
          :sub="`样本 ${stats?.with_t1 ?? 0}`"
          format="raw"
        />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          label="T+7 平均变动"
          :value="moveText(stats?.avg_move_t7_pct)"
          :sub="`样本 ${stats?.with_t7 ?? 0}`"
          format="raw"
        />
      </el-col>
      <el-col :span="6">
        <StatisticCard
          label="T+30 平均变动"
          :value="moveText(stats?.avg_move_t30_pct)"
          :sub="`样本 ${stats?.with_t30 ?? 0}`"
          format="raw"
        />
      </el-col>
    </el-row>

    <el-card class="table-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">历史记录</span>
          <div class="filters">
            <el-select v-model="filterKind" clearable placeholder="全部语境" size="small">
              <el-option value="pre_purchase" label="购买前" />
              <el-option value="post_purchase" label="购买后" />
              <el-option value="plan_execution" label="计划执行" />
            </el-select>
            <el-select v-model="filterStatus" clearable placeholder="全部状态" size="small">
              <el-option value="delivered" label="已给出" />
              <el-option value="acknowledged" label="已读" />
              <el-option value="acted" label="已执行" />
              <el-option value="suppressed" label="未推送" />
            </el-select>
          </div>
        </div>
      </template>

      <el-table :data="items" size="small" empty-text="还没有建议记录">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-body">
              <AdviceCard :advice="row as AdviceRecord" title="记录详情" @changed="loadAll" />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="语境" width="92">
          <template #default="{ row }">{{ kindLabel(row.kind) }}</template>
        </el-table-column>
        <el-table-column label="动作" width="128">
          <template #default="{ row }">
            <el-tag size="small" :type="actionTagType(row.action)">
              {{ actionLabel(row.action) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="90" align="right">
          <template #default="{ row }">
            {{ row.target_grams ? `${row.target_grams} g` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="当时价格" width="110" align="right">
          <template #default="{ row }">
            {{ row.price_at_advice != null ? `¥${row.price_at_advice.toFixed(2)}` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="T+1" width="150">
          <template #default="{ row }">
            {{ reviewMoveText(row.action, movePct(row.price_at_advice, row.price_t1)) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.rationale }}</template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > pageSize"
        class="pagination"
        layout="prev, pager, next, total"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        @current-change="onPageChange"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faClockRotateLeft, faRotate } from '@fortawesome/free-solid-svg-icons'
import { adviceApi } from '@/api/modules/advice'
import type {
  AdviceAction,
  AdviceKind,
  AdviceRecord,
  AdviceReviewStats,
  AdviceStatus
} from '@/api/modules/advice'
import {
  ACTION_LABELS,
  ACTION_TAG_TYPES,
  KIND_LABELS,
  STATUS_LABELS,
  STATUS_TAG_TYPES,
  reviewMoveText
} from '@/utils/adviceHelpers'
import StatisticCard from '@/components/StatisticCard.vue'
import AdviceCard from '@/components/AdviceCard.vue'

library.add(faClockRotateLeft, faRotate)

const loading = ref(false)
const refreshing = ref(false)
const items = ref<AdviceRecord[]>([])
const stats = ref<AdviceReviewStats | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterKind = ref<AdviceKind | undefined>()
const filterStatus = ref<AdviceStatus | undefined>()

function actionLabel(action: AdviceAction) {
  return ACTION_LABELS[action] ?? action
}

function actionTagType(action: AdviceAction) {
  return ACTION_TAG_TYPES[action] ?? 'info'
}

function kindLabel(kind: AdviceKind) {
  return KIND_LABELS[kind] ?? kind
}

function statusLabel(status: AdviceStatus) {
  return STATUS_LABELS[status] ?? status
}

function statusTagType(status: AdviceStatus) {
  return STATUS_TAG_TYPES[status] ?? 'info'
}

function movePct(from: number | null, to: number | null): number | null {
  if (from === null || to === null || from <= 0) return null
  return ((to - from) / from) * 100
}

function moveText(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

async function loadHistory() {
  const response = await adviceApi.getHistory({
    kind: filterKind.value,
    status: filterStatus.value,
    page: page.value,
    page_size: pageSize.value
  })
  items.value = response.items
  total.value = response.total
}

async function loadStats() {
  stats.value = await adviceApi.getReviewStats()
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadHistory(), loadStats()])
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function refreshReviews() {
  refreshing.value = true
  try {
    const result = await adviceApi.refreshReviews()
    ElMessage.success(`已回填 ${result.filled} 条回访价格`)
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    refreshing.value = false
  }
}

function onPageChange(next: number) {
  page.value = next
  loadAll()
}

watch([filterKind, filterStatus], () => {
  page.value = 1
  loadAll()
})

onMounted(loadAll)
</script>

<style lang="scss" scoped>
.advice-history {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
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
}

.stat-row {
  margin-bottom: 20px;
}

.table-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .card-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .filters {
    display: flex;
    gap: 8px;
  }

  .pagination {
    margin-top: 16px;
    justify-content: flex-end;
  }
}

.expand-body {
  padding: 12px 16px 0;

  :deep(.advice-card) {
    margin-bottom: 8px;
  }
}
</style>
