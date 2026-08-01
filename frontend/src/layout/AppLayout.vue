<template>
  <el-container class="app-layout">
    <AppSidebar v-model:is-collapse="isCollapse" />

    <el-container>
      <el-header class="app-titlebar">
        <div class="titlebar-left">
          <font-awesome-icon
            :icon="isCollapse ? 'angles-right' : 'angles-left'"
            class="collapse-btn"
            @click="isCollapse = !isCollapse"
          />
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.path !== '/'">
              {{ breadcrumbTitle }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="titlebar-right">
          <font-awesome-icon icon="sun" class="theme-icon" />
          <el-switch v-model="isDark" @change="themeStore.toggle()" />
          <font-awesome-icon icon="moon" class="theme-icon" />
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faAnglesLeft, faAnglesRight, faMoon, faSun } from '@fortawesome/free-solid-svg-icons'
import { useThemeStore } from '@/stores/theme'
import AppSidebar from '@/layout/AppSidebar.vue'

library.add(faAnglesLeft, faAnglesRight, faMoon, faSun)

const route = useRoute()
const themeStore = useThemeStore()
const isCollapse = ref(false)

const isDark = computed({
  get: () => themeStore.current === 'dark',
  set: () => {},
})

const breadcrumbTitle = computed(() => {
  const titles: Record<string, string> = {
    '/dashboard': '监控面板',
    '/price-history': '价格历史',
    '/providers': '模型池',
    '/logs': '系统日志',
    '/ai-stats': 'AI 调用统计',
    '/notification-stats': '通知统计',
    '/settings': '设置',
  }
  return titles[route.path] || ''
})
</script>

<style lang="scss" scoped>
.app-layout {
  height: 100vh;
}

.app-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--titlebar-bg);
  border-bottom: 1px solid var(--titlebar-border);
  box-shadow: var(--shadow-sm);
  transition:
    background 0.3s,
    border-color 0.3s;

  .titlebar-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .collapse-btn {
    cursor: pointer;
    color: var(--text-secondary);
    &:hover {
      color: var(--color-primary);
    }
  }

  .titlebar-right {
    display: flex;
    align-items: center;
    gap: 8px;

    .theme-icon {
      font-size: 14px;
      color: var(--text-secondary);
    }
  }
}

.app-main {
  background: var(--bg-page);
  padding: 20px;
  transition: background 0.3s;
}
</style>
