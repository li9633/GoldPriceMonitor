<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="cog" /> 系统设置</h1>
    </div>

    <el-card class="main-card">
      <div class="settings-layout">
        <div class="settings-sidebar">
          <div class="sidebar-group">基础设施</div>
          <div
            v-for="tab in infrastructureTabs"
            :key="tab.key"
            class="sidebar-item"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <font-awesome-icon :icon="tab.icon" class="sidebar-icon" />
            <span>{{ tab.label }}</span>
          </div>
          <div class="sidebar-group">核心业务</div>
          <div
            v-for="tab in businessTabs"
            :key="tab.key"
            class="sidebar-item"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <font-awesome-icon :icon="tab.icon" class="sidebar-icon" />
            <span>{{ tab.label }}</span>
          </div>
          <div class="sidebar-group">通知与消息</div>
          <div
            v-for="tab in notificationTabs"
            :key="tab.key"
            class="sidebar-item"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <font-awesome-icon :icon="tab.icon" class="sidebar-icon" />
            <span>{{ tab.label }}</span>
          </div>
          <div class="sidebar-group">智能与日志</div>
          <div
            v-for="tab in aiLogTabs"
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faCog,
  faBell,
  faRobot,
  faEnvelope,
  faEye,
  faComment,
  faTags,
  faFile,
  faServer,
} from '@fortawesome/free-solid-svg-icons'

library.add(faCog, faBell, faRobot, faEnvelope, faEye, faComment, faTags, faFile, faServer)

const activeTab = ref('infrastructure')

const infrastructureTabs = [{ key: 'infrastructure', label: '基础设施', icon: 'server' }]

const businessTabs = [
  { key: 'monitor', label: '监控配置', icon: 'eye' },
  { key: 'alert', label: '报警配置', icon: 'bell' },
  { key: 'symbols', label: '品种映射', icon: 'tags' },
]

const notificationTabs = [
  { key: 'notification', label: '通知配置', icon: 'envelope' },
  { key: 'message', label: '消息模板', icon: 'comment' },
]

const aiLogTabs = [
  { key: 'ai', label: 'AI 配置', icon: 'robot' },
  { key: 'log', label: '日志配置', icon: 'file' },
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

.sidebar-group {
  padding: 16px 20px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
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
