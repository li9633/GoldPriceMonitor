<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="cog" /> 系统设置</h1>
    </div>

    <el-card v-if="exchangeRate" class="rate-card">
      <template #header>
        <span><font-awesome-icon icon="dollar-sign" /> 汇率缓存</span>
      </template>
      <div class="rate-body">
        <div class="rate-info">
          <span class="rate-label">当前汇率</span>
          <span class="rate-value">{{ exchangeRate.rate?.toFixed(6) ?? '暂无数据' }}</span>
          <span v-if="exchangeRate.updated_at" class="rate-time">
            更新于 {{ exchangeRate.updated_at }}
          </span>
        </div>
        <el-button text type="primary" :loading="updatingRate" @click="showRateDialog = true">
          <font-awesome-icon icon="pen" /> 手动更新
        </el-button>
      </div>
    </el-card>

    <el-card class="main-card">
      <div class="settings-layout">
        <div class="settings-sidebar">
          <div
            v-for="tab in tabs"
            :key="tab.key"
            class="sidebar-item"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <font-awesome-icon :icon="tab.icon" class="sidebar-icon" />
            <span>{{ tab.label }}</span>
          </div>
        </div>
        <div class="settings-content">
          <component :is="currentComponent" :key="activeTab" />
        </div>
      </div>
    </el-card>

    <el-dialog v-model="showRateDialog" title="手动更新汇率" width="400px">
      <el-form label-width="100px">
        <el-form-item label="新汇率">
          <el-input-number v-model="rateInput" :min="1" :max="20" :precision="6" :step="0.0001" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRateDialog = false">取消</el-button>
        <el-button type="primary" :loading="updatingRate" @click="handleUpdateRate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, defineAsyncComponent } from 'vue'
import { ElMessage } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faCog,
  faDollarSign,
  faPen,
  faBell,
  faRobot,
  faEnvelope,
  faEye,
  faComment,
  faTags,
  faFile,
  faServer,
} from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import type { ExchangeRate } from '@/api/modules/settings'

library.add(
  faCog,
  faDollarSign,
  faPen,
  faBell,
  faRobot,
  faEnvelope,
  faEye,
  faComment,
  faTags,
  faFile,
  faServer,
)

const activeTab = ref('alert')

const tabs = [
  { key: 'alert', label: '报警配置', icon: 'bell' },
  { key: 'ai', label: 'AI 配置', icon: 'robot' },
  { key: 'notification', label: '通知配置', icon: 'envelope' },
  { key: 'monitor', label: '监控配置', icon: 'eye' },
  { key: 'message', label: '消息模板', icon: 'comment' },
  { key: 'symbols', label: '品种映射', icon: 'tags' },
  { key: 'log', label: '日志配置', icon: 'file' },
  { key: 'infrastructure', label: '基础设施', icon: 'server' },
]

const tabComponents: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  alert: defineAsyncComponent(() => import('@/components/settings/AlertSettings.vue')),
  ai: defineAsyncComponent(() => import('@/components/settings/AiSettings.vue')),
  notification: defineAsyncComponent(
    () => import('@/components/settings/NotificationSettings.vue'),
  ),
  monitor: defineAsyncComponent(() => import('@/components/settings/MonitorSettings.vue')),
  message: defineAsyncComponent(() => import('@/components/settings/MessageSettings.vue')),
  symbols: defineAsyncComponent(() => import('@/components/settings/SymbolSettings.vue')),
  log: defineAsyncComponent(() => import('@/components/settings/LogSettings.vue')),
  infrastructure: defineAsyncComponent(
    () => import('@/components/settings/InfrastructureSettings.vue'),
  ),
}

const currentComponent = computed(() => tabComponents[activeTab.value])

const exchangeRate = ref<ExchangeRate | null>(null)
const updatingRate = ref(false)
const showRateDialog = ref(false)
const rateInput = ref(0)

async function loadExchangeRate() {
  try {
    exchangeRate.value = await settingsApi.getExchangeRate()
  } catch {
    // ignore
  }
}

async function handleUpdateRate() {
  updatingRate.value = true
  try {
    await settingsApi.updateExchangeRate(rateInput.value)
    ElMessage.success('汇率更新成功')
    showRateDialog.value = false
    await loadExchangeRate()
  } catch {
    // ignore
  } finally {
    updatingRate.value = false
  }
}

onMounted(loadExchangeRate)
</script>

<style lang="scss" scoped>
.settings {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }
}

.rate-card {
  margin-bottom: 20px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .rate-body {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .rate-info {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .rate-label {
    font-size: 14px;
    color: var(--text-secondary);
  }

  .rate-value {
    font-size: 22px;
    font-weight: bold;
    color: var(--price-color);
  }

  .rate-time {
    font-size: 13px;
    color: var(--text-muted);
  }
}

.settings-layout {
  display: flex;
  gap: 0;
  min-height: 500px;
}

.settings-sidebar {
  width: 160px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-color);
  padding: 8px 0;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  border-right: 2px solid transparent;
  margin-right: -1px;

  &:hover {
    color: var(--text-primary);
    background: var(--bg-secondary);
  }

  &.active {
    color: var(--color-primary);
    background: rgba(var(--color-primary-rgb, 64, 158, 255), 0.06);
    border-right-color: var(--color-primary);
    font-weight: 500;
  }

  .sidebar-icon {
    width: 16px;
    text-align: center;
  }
}

.settings-content {
  flex: 1;
  padding: 16px 24px;
  overflow: auto;
}
</style>
