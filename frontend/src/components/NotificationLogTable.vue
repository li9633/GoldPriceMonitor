<template>
  <el-card shadow="hover" class="logs-card">
    <template #header>
      <span class="card-title">发送记录</span>
    </template>
    <el-table :data="items" stripe size="small" v-loading="loading">
      <el-table-column prop="created_at" label="时间" width="160" />
      <el-table-column prop="channel_name" label="渠道" width="100" />
      <el-table-column prop="symbol_name" label="品种" width="100" />
      <el-table-column label="级别" width="80">
        <template #default="{ row }">
          <el-tag
            :type="
              row.alert_level === 'critical'
                ? 'danger'
                : row.alert_level === 'warning'
                  ? 'warning'
                  : 'info'
            "
            size="small"
          >
            {{ row.alert_level }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="alert_summary" label="摘要" min-width="200" show-overflow-tooltip />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.success ? 'success' : 'danger'" size="small">
            {{ row.success ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="延迟" width="80">
        <template #default="{ row }">
          {{ row.latency_ms != null ? row.latency_ms.toFixed(0) + 'ms' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="链路" width="100">
        <template #default="{ row }">
          <el-button
            v-if="row.chain_total > 1"
            text
            type="primary"
            size="small"
            @click="openChain(row.chain_id)"
          >
            查看 ({{ row.chain_position + 1 }}/{{ row.chain_total }})
          </el-button>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="$emit('pageChange', $event)"
        @size-change="$emit('pageSizeChange', $event)"
      />
    </div>

    <el-dialog v-model="chainVisible" title="降级链路详情" width="700px">
      <el-table :data="chainDetails" stripe size="small">
        <el-table-column label="顺序" width="60">
          <template #default="{ row }"> {{ row.chain_position + 1 }} </template>
        </el-table-column>
        <el-table-column prop="channel_name" label="渠道" width="100" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="延迟" width="80">
          <template #default="{ row }">
            {{ row.latency_ms != null ? row.latency_ms.toFixed(0) + 'ms' : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="error_type" label="错误类型" width="100" />
        <el-table-column
          prop="error_reason"
          label="错误详情"
          min-width="200"
          show-overflow-tooltip
        />
      </el-table>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { notificationStatsApi } from '@/api/modules/notification'
import type { NotifyLogItem } from '@/api/modules/notification'

defineProps<{
  items: NotifyLogItem[]
  total: number
  loading: boolean
}>()

defineEmits<{ pageChange: [page: number]; pageSizeChange: [size: number] }>()

const page = ref(1)
const pageSize = ref(20)
const chainVisible = ref(false)
const chainDetails = ref<NotifyLogItem[]>([])

const openChain = async (chainId: string) => {
  try {
    chainDetails.value = await notificationStatsApi.getChain(chainId)
    chainVisible.value = true
  } catch {
    /* ignore */
  }
}
</script>

<style lang="scss" scoped>
.card-title {
  font-weight: 600;
}

.logs-card {
  margin-bottom: 20px;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
