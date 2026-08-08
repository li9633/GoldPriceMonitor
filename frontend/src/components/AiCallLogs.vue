<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title"> <font-awesome-icon icon="list" /> 调用日志 </span>
    </template>
    <el-table :data="items" size="small" empty-text="暂无记录" @row-click="showDetail">
      <el-table-column label="时间" prop="call_time" width="160" />
      <el-table-column label="供应商" prop="provider_name" min-width="80" />
      <el-table-column label="模型" prop="model_name" min-width="110" />
      <el-table-column label="状态" width="70" align="center">
        <template #default="{ row }">
          <font-awesome-icon
            v-if="row.from_cache"
            icon="box-archive"
            class="status-cache"
            title="缓存命中"
          />
          <font-awesome-icon v-else-if="row.success" icon="circle-check" class="status-success" />
          <font-awesome-icon v-else icon="circle-xmark" class="status-failure" />
        </template>
      </el-table-column>
      <el-table-column label="延迟" width="80" align="right">
        <template #default="{ row }">
          <span :style="{ color: latencyColor(row.latency_ms ?? 0) }">
            {{ row.latency_ms != null ? row.latency_ms + 'ms' : '-' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="失败原因" min-width="140">
        <template #default="{ row }">
          <span class="error-reason">{{ row.error_reason || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Token" width="120" align="right">
        <template #default="{ row }">
          <span v-if="row.total_tokens" class="token-cell">
            {{ row.total_tokens.toLocaleString() }}
          </span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="缓存" width="60" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.from_cache" type="info" size="small">是</el-tag>
          <span v-else class="text-muted">否</span>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="调用详情" width="520px" class="call-detail-dialog">
      <template v-if="selectedRow">
        <div class="detail-row">
          <span class="detail-label">ID</span><span>{{ selectedRow.id }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">时间</span><span>{{ selectedRow.call_time }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">供应商</span><span>{{ selectedRow.provider_name }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">模型</span><span>{{ selectedRow.model_name }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">状态</span>
          <span :style="{ color: selectedRow.success ? '#67c23a' : '#f56c6c' }">
            {{ selectedRow.from_cache ? '缓存命中' : selectedRow.success ? '成功' : '失败' }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">延迟</span
          ><span>{{ selectedRow.latency_ms != null ? selectedRow.latency_ms + 'ms' : '-' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">失败原因</span
          ><span class="error-reason">{{ selectedRow.error_reason || '-' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">输入Token</span
          ><span>{{ selectedRow.prompt_tokens.toLocaleString() }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">输出Token</span
          ><span>{{ selectedRow.completion_tokens.toLocaleString() }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">总Token</span
          ><span>{{ selectedRow.total_tokens.toLocaleString() }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">触发报警</span
          ><span>{{ selectedRow.triggered_alerts || '-' }}</span>
        </div>
        <div class="detail-row" style="margin-top: 8px">
          <span class="detail-label">原始响应</span>
          <pre class="raw-response">{{ selectedRow.raw_response || '-' }}</pre>
        </div>
      </template>
      <template #footer>
        <el-button type="primary" @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="fetchData"
        @size-change="onPageSizeChange"
      />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faList,
  faCircleCheck,
  faCircleXmark,
  faBoxArchive,
} from '@fortawesome/free-solid-svg-icons'
import { aiStatsApi } from '@/api/modules/ai-stats'
import type { AiCallLogItem, DateParams } from '@/api/modules/ai-stats'
import { latencyColor } from '@/utils/aiStatsHelpers'

library.add(faList, faCircleCheck, faCircleXmark, faBoxArchive)

const props = defineProps<{
  dateParams: DateParams
}>()

const items = ref<AiCallLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

async function fetchData() {
  try {
    const res = await aiStatsApi.getLogs(page.value, pageSize.value, props.dateParams)
    items.value = res.items
    total.value = res.total
  } catch {
    // ignore
  }
}

function onPageSizeChange() {
  page.value = 1
  fetchData()
}

import { watch } from 'vue'

const selectedRow = ref<AiCallLogItem | null>(null)
const dialogVisible = ref(false)

function showDetail(row: AiCallLogItem) {
  selectedRow.value = row
  dialogVisible.value = true
}

watch(
  () => props.dateParams,
  () => {
    page.value = 1
    fetchData()
  },
)

onMounted(fetchData)

defineExpose({ fetchData })
</script>

<style lang="scss" scoped>
.card-title {
  font-weight: 600;
}

.status-success {
  color: #67c23a;
}

.status-failure {
  color: #f56c6c;
}

.status-cache {
  color: #409eff;
}

.error-reason {
  color: #f56c6c;
  font-size: 12px;
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.token-cell {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.pagination-bar {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

:deep(.el-table__row) {
  cursor: pointer;

  &:hover > td {
    background-color: var(--el-color-primary-light-9) !important;
  }
}

:deep(.el-table__cell .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style lang="scss">
.call-detail-dialog {
  .detail-row {
    display: flex;
    margin-bottom: 6px;
    font-size: 14px;
    line-height: 1.6;

    .detail-label {
      flex-shrink: 0;
      width: 80px;
      color: var(--el-text-color-secondary);
    }
  }

  .raw-response {
    margin: 4px 0 0;
    padding: 8px;
    background: var(--el-fill-color-light);
    border-radius: 4px;
    font-size: 12px;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
  }
}
</style>
