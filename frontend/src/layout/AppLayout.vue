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
          <el-icon><Monitor /></el-icon>
          <template #title>监控面板</template>
        </el-menu-item>
        <el-menu-item index="/price-history">
          <el-icon><TrendCharts /></el-icon>
          <template #title>价格历史</template>
        </el-menu-item>
        <el-menu-item index="/providers">
          <el-icon><Connection /></el-icon>
          <template #title>模型池</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>设置</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-titlebar">
        <div class="titlebar-left">
          <el-icon class="collapse-btn" :size="20" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="activeMenu !== '/'">
              {{ breadcrumbTitle }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="titlebar-right">
          <el-switch
            v-model="isDark"
            :active-icon="Moon"
            :inactive-icon="Sunny"
            inline-prompt
            @change="themeStore.toggle()"
          />
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
import { faTrophy, faCoins } from '@fortawesome/free-solid-svg-icons'
import {
  Monitor,
  TrendCharts,
  Setting,
  Fold,
  Expand,
  Moon,
  Sunny,
  Connection,
} from '@element-plus/icons-vue'
import { useThemeStore } from '@/stores/theme'

library.add(faTrophy, faCoins)

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
    gap: 16px;
  }
}

.app-main {
  background: var(--bg-page);
  padding: 20px;
  transition: background 0.3s;
}
</style>
