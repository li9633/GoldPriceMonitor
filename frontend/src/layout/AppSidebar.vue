<template>
  <el-aside :width="isCollapse ? '64px' : '220px'" class="app-sidebar">
    <div class="sidebar-logo" @click="$emit('update:isCollapse', !isCollapse)">
      <span v-show="!isCollapse"><font-awesome-icon icon="trophy" /> 黄金监控</span>
      <span v-show="isCollapse"><font-awesome-icon icon="trophy" /></span>
    </div>
    <el-menu
      :default-active="activeMenu"
      :default-openeds="['monitor', 'stats', 'system']"
      :collapse="isCollapse"
      :collapse-transition="false"
      router
    >
      <el-sub-menu index="monitor">
        <template #title>
          <font-awesome-icon icon="chart-simple" class="menu-icon" />
          <span class="menu-text">监控与数据</span>
        </template>
        <el-menu-item index="/dashboard">
          <font-awesome-icon icon="desktop" class="menu-icon" />
          <span class="menu-text">监控面板</span>
        </el-menu-item>
        <el-menu-item index="/price-history">
          <font-awesome-icon icon="chart-line" class="menu-icon" />
          <span class="menu-text">价格历史</span>
        </el-menu-item>
        <el-menu-item index="/exchange-rate">
          <font-awesome-icon icon="dollar-sign" class="menu-icon" />
          <span class="menu-text">汇率行情</span>
        </el-menu-item>
      </el-sub-menu>
      <el-sub-menu index="stats">
        <template #title>
          <font-awesome-icon icon="chart-pie" class="menu-icon" />
          <span class="menu-text">统计与分析</span>
        </template>
        <el-menu-item index="/ai-stats">
          <font-awesome-icon icon="robot" class="menu-icon" />
          <span class="menu-text">AI 调用统计</span>
        </el-menu-item>
        <el-menu-item index="/notification-stats">
          <font-awesome-icon icon="bell" class="menu-icon" />
          <span class="menu-text">通知统计</span>
        </el-menu-item>
      </el-sub-menu>
      <el-sub-menu index="system">
        <template #title>
          <font-awesome-icon icon="sliders" class="menu-icon" />
          <span class="menu-text">系统管理</span>
        </template>
        <el-menu-item index="/providers">
          <font-awesome-icon icon="diagram-project" class="menu-icon" />
          <span class="menu-text">模型池</span>
        </el-menu-item>
        <el-menu-item index="/logs">
          <font-awesome-icon icon="file-lines" class="menu-icon" />
          <span class="menu-text">系统日志</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <font-awesome-icon icon="gear" class="menu-icon" />
          <span class="menu-text">系统设置</span>
        </el-menu-item>
      </el-sub-menu>
    </el-menu>
  </el-aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faTrophy,
  faDesktop,
  faChartLine,
  faChartSimple,
  faChartPie,
  faDiagramProject,
  faFileLines,
  faGear,
  faRobot,
  faBell,
  faSliders,
  faDollarSign,
} from '@fortawesome/free-solid-svg-icons'

library.add(
  faTrophy,
  faDesktop,
  faChartLine,
  faChartSimple,
  faChartPie,
  faDiagramProject,
  faFileLines,
  faGear,
  faRobot,
  faBell,
  faSliders,
  faDollarSign,
)

defineProps<{ isCollapse: boolean }>()
defineEmits<{ 'update:isCollapse': [value: boolean] }>()

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style lang="scss" scoped>
.app-sidebar {
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  transition:
    width 0.3s,
    background-color 0.3s;
  overflow: hidden;

  .menu-icon {
    margin-right: 8px;
    width: 1em;
    text-align: center;
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
    overflow: hidden;
  }

  // 菜单项
  :deep(.el-menu-item) {
    margin: 0 16px;
    border-radius: 6px;

    &.is-active {
      background-color: transparent !important;
    }

    &.is-active:hover {
      background-color: var(--sidebar-hover-bg) !important;
    }
  }

  // 子菜单标题
  :deep(.el-sub-menu__title) {
    margin: 0 16px;
    border-radius: 6px;
  }

  // 子菜单内的菜单项增加左侧缩进
  :deep(.el-sub-menu .el-menu-item) {
    padding-left: 40px !important;
  }
}
</style>
