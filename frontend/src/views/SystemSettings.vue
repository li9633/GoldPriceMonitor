<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="cog" /> 系统设置</h1>
      <el-button type="primary" :loading="reloading" @click="handleReload">
        <font-awesome-icon icon="rotate" /> 刷新缓存
      </el-button>
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
      <el-tabs v-model="activeTab">
        <el-tab-pane label="报警配置" name="alert" />
        <el-tab-pane label="AI 配置" name="ai" />
        <el-tab-pane label="企业微信" name="wechat" />
        <el-tab-pane label="邮件配置" name="email" />
        <el-tab-pane label="监控配置" name="monitor" />
        <el-tab-pane label="消息模板" name="message" />
        <el-tab-pane label="品种映射" name="symbols" />
        <el-tab-pane label="日志配置" name="log" />
        <el-tab-pane label="基础设施" name="infrastructure" />
      </el-tabs>

      <component :is="currentComponent" :key="activeTab" class="tab-content" />
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
import { faCog, faRotate, faDollarSign, faPen } from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import type { ExchangeRate } from '@/api/modules/settings'

library.add(faCog, faRotate, faDollarSign, faPen)

const activeTab = ref('alert')

const tabComponents: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  alert: defineAsyncComponent(() => import('@/components/settings/AlertSettings.vue')),
  ai: defineAsyncComponent(() => import('@/components/settings/AiSettings.vue')),
  wechat: defineAsyncComponent(() => import('@/components/settings/WechatSettings.vue')),
  email: defineAsyncComponent(() => import('@/components/settings/EmailSettings.vue')),
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
const reloading = ref(false)
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

async function handleReload() {
  reloading.value = true
  try {
    await settingsApi.reload()
    ElMessage.success('缓存已刷新')
  } catch {
    // ignore
  } finally {
    reloading.value = false
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
  max-width: 960px;
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

.tab-content {
  padding-top: 16px;
}
</style>
