<template>
  <el-card shadow="hover">
    <template #header>
      <span class="card-title"> <font-awesome-icon icon="list" /> 调用日志 </span>
    </template>
    <el-table :data="items" size="small" empty-text="暂无记录">
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
      <el-table-column label="失败原因" prop="error_reason" min-width="160">
        <template #default="{ row }">
          <span class="error-reason">{{ row.error_reason || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="缓存" width="60" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.from_cache" type="info" size="small">是</el-tag>
          <span v-else class="text-muted">否</span>
        </template>
      </el-table-column>
    </el-table>
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
import type { AiCallLogItem } from '@/api/modules/ai-stats'
import { latencyColor } from '@/utils/aiStatsHelpers'

library.add(faList, faCircleCheck, faCircleXmark, faBoxArchive)

const items = ref<AiCallLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

async function fetchData() {
  try {
    const res = await aiStatsApi.getLogs(page.value, pageSize.value)
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

onMounted(fetchData)
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

.pagination-bar {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
