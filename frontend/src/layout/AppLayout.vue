<template>
  <el-container class="app-layout">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="app-sidebar">
      <div class="sidebar-logo" @click="isCollapse = !isCollapse">
        <span v-show="!isCollapse"><font-awesome-icon icon="trophy" /> 黄金监控</span>
        <span v-show="isCollapse"><font-awesome-icon icon="trophy" /></span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        router
      >
        <el-menu-item index="/dashboard">
          <font-awesome-icon icon="desktop" class="menu-icon" />
          <template #title>
            <span class="menu-text">监控面板</span>
          </template>
        </el-menu-item>
        <el-menu-item index="/price-history">
          <font-awesome-icon icon="chart-line" class="menu-icon" />
          <template #title>
            <span class="menu-text">价格历史</span>
          </template>
        </el-menu-item>
        <el-menu-item index="/providers">
          <font-awesome-icon icon="diagram-project" class="menu-icon" />
          <template #title>
            <span class="menu-text">模型池</span>
          </template>
        </el-menu-item>
        <el-menu-item index="/logs">
          <font-awesome-icon icon="file-lines" class="menu-icon" />
          <template #title>
            <span class="menu-text">系统日志</span>
          </template>
        </el-menu-item>
        <el-menu-item index="/ai-stats">
          <font-awesome-icon icon="robot" class="menu-icon" />
          <template #title>
            <span class="menu-text">AI 调用统计</span>
          </template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <font-awesome-icon icon="gear" class="menu-icon" />
          <template #title>
            <span class="menu-text">设置</span>
          </template>
        </el-menu-item>
      </el-menu>
    </el-aside>

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
            <el-breadcrumb-item v-if="activeMenu !== '/'">
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
import {
  faTrophy,
  faDesktop,
  faChartLine,
  faDiagramProject,
  faFileLines,
  faGear,
  faAnglesLeft,
  faAnglesRight,
  faMoon,
  faSun,
  faRobot,
} from '@fortawesome/free-solid-svg-icons'
import { useThemeStore } from '@/stores/theme'

library.add(
  faTrophy,
  faDesktop,
  faChartLine,
  faDiagramProject,
  faFileLines,
  faGear,
  faAnglesLeft,
  faAnglesRight,
  faMoon,
  faSun,
  faRobot,
)

const route = useRoute()
const themeStore = useThemeStore()
const isCollapse = ref(false)

const activeMenu = computed(() => route.path)
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
    '/settings': '设置',
  }
  return titles[route.path] || ''
})
</script>

<style lang="scss" scoped>
.app-layout {
  height: 100vh;
}

.app-sidebar {
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  transition:
    width 0.3s,
    background-color 0.3s;
  overflow: hidden;

  .menu-icon {
    margin-right: 8px;
  }

  .menu-text {
    font-size: 14px;
  }

  .sidebar-logo {
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--sidebar-logo-color);
    font-size: 18px;
    font-weight: bold;
    cursor: pointer;
    border-bottom: 1px solid var(--sidebar-border);
    transition: color 0.3s;
  }

  .el-menu {
    border-right: none;
  }
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
