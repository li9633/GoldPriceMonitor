<template>
  <div v-loading="loading" class="tab-content">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="数据源为只读配置。变更数据源或解析逻辑需修改 backend/providers/ 后重启服务，主备切换由系统按健康状态自动进行。"
      class="log-notice"
    />

    <template v-if="infrastructure">
      <!-- 数据源 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">数据源</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="金价数据源">
            <div class="source-chain">
              <div
                v-for="s in infrastructure.gold_price_sources"
                :key="s.name"
                class="source-row"
              >
                <el-tag :type="s.active ? 'success' : 'info'" size="small">
                  {{ s.active ? '生效中' : s.role }}
                </el-tag>
                <span class="source-name">{{ s.name }}</span>
                <code>{{ s.api_url }}</code>
              </div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="汇率数据源">
            <div class="source-chain">
              <div
                v-for="s in infrastructure.exchange_rate_sources"
                :key="s.name"
                class="source-row"
              >
                <el-tag :type="s.active ? 'success' : 'info'" size="small">
                  {{ s.active ? '生效中' : s.role }}
                </el-tag>
                <span class="source-name">{{ s.name }}</span>
                <code>{{ s.api_url }}</code>
              </div>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 交易日历 -->
      <el-card shadow="never" class="infra-section">
        <template #header><span class="section-title">交易日历</span></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="权威源">{{ calendar?.primary_source || '—' }}</el-descriptions-item>
          <el-descriptions-item label="在线源">{{ calendar?.online_source || '—' }}</el-descriptions-item>
          <el-descriptions-item label="当前生效">
            <template v-if="calendar">
              <el-tag :type="calendar.degraded ? 'warning' : 'success'" size="small">
                {{ calendar.degraded ? '已降级' : '正常' }}
              </el-tag>
              <span class="source-name">{{ calendar.active_source }}</span>
            </template>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="缓存天数">
            {{ calendar ? `${calendar.cached_days} 天（在线结果已落库）` : '—' }}
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="calendar?.degraded"
          type="warning"
          :closable="false"
          show-icon
          class="cal-warning"
          title="节假日判定已降级（权威库未覆盖该年份且在线源不可用），法定节假日与调休可能无法识别，请升级 chinese-calendar 或检查网络。"
        />
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
import type { InfrastructureConfig, CalendarStatus } from '@/api/modules/settings'

const infrastructure = ref<InfrastructureConfig | null>(null)
const calendar = ref<CalendarStatus | null>(null)
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
  // 日历状态失败不阻塞页面（独立请求，缺省显示 —）
  try {
    calendar.value = await settingsApi.getCalendarStatus()
  } catch {
    /* ignore */
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

  .source-chain {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .source-row {
      display: flex;
      align-items: center;
      gap: 8px;

      .source-name {
        font-weight: 600;
        font-size: 13px;
        color: var(--text-primary);
        min-width: 130px;
      }
    }
  }

  .cal-warning {
    margin-top: 12px;
  }
}
</style>
