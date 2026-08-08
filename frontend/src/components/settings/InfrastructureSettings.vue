<template>
  <div v-loading="loading" class="tab-content">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="只读端点，API URL 变更需同步修改解析逻辑，请在 config.py 中修改后重启。"
      class="log-notice"
    />

    <template v-if="infrastructure">
      <!-- API 端点 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">API 端点</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="金价数据源">
            <code>{{ infrastructure.gold_price_api_url }}</code>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 系统配置 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">系统配置</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="时区">{{ infrastructure.timezone }}</el-descriptions-item>
          <el-descriptions-item v-if="infrastructure.debug_mode" label="调试模式">
            <el-tag type="warning" size="small">开启</el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 日志 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">日志</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="存储目录">
            <code>{{ infrastructure.log_dir }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="占用空间">
            {{ formatBytes(infrastructure.log_dir_size_bytes) }}
          </el-descriptions-item>
          <el-descriptions-item label="文件列表">
            <span class="file-count">共 {{ infrastructure.log_file_count }} 个文件</span>
            <div class="file-list">
              <el-tag v-for="f in infrastructure.log_files" :key="f" size="small" type="info">{{
                f
              }}</el-tag>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 数据库 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">数据库</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="数据目录">
            <code>{{ infrastructure.db_dir }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="占用空间">
            {{ formatBytes(infrastructure.db_dir_size_bytes) }}
          </el-descriptions-item>
          <el-descriptions-item label="文件列表">
            <span class="file-count">共 {{ infrastructure.db_file_count }} 个文件</span>
            <div class="file-list">
              <el-tag v-for="f in infrastructure.db_files" :key="f" size="small" type="info">{{
                f
              }}</el-tag>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { settingsApi } from '@/api/modules/settings'
import type { InfrastructureConfig } from '@/api/modules/settings'

const infrastructure = ref<InfrastructureConfig | null>(null)
const loading = ref(false)

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i]
}

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

.infra-section {
  margin-bottom: 16px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .section-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
  }

  code {
    background: var(--bg-secondary);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 13px;
    word-break: break-all;
  }

  .file-count {
    display: block;
    margin-bottom: 6px;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .file-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
}
</style>
