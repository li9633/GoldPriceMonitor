<template>
  <div v-loading="loading" class="tab-content">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="只读端点，API URL 变更需同步修改解析逻辑，请在 config.py 中修改后重启。"
      class="log-notice"
    />
    <el-descriptions v-if="infrastructure" :column="1" border class="infra-descriptions">
      <el-descriptions-item label="金价数据源 API">
        <code>{{ infrastructure.gold_price_api_url }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="美元汇率 API">
        <code>{{ infrastructure.usd_to_cny_api_url }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="系统时区">
        {{ infrastructure.timezone }}
      </el-descriptions-item>
      <el-descriptions-item label="日志存储目录">
        <code>{{ infrastructure.log_dir }}</code>
      </el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { settingsApi } from '@/api/modules/settings'
import type { InfrastructureConfig } from '@/api/modules/settings'

const infrastructure = ref<InfrastructureConfig | null>(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    infrastructure.value = await settingsApi.getInfrastructure()
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;

  .log-notice {
    margin-bottom: 20px;
  }
}

.infra-descriptions {
  margin-top: 8px;

  code {
    background: var(--bg-secondary);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 13px;
    word-break: break-all;
  }
}
</style>
