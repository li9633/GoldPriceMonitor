<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="cog" /> 系统设置</h1>
    </div>

    <el-card class="setting-card">
      <template #header><span>监控配置</span></template>
      <el-form label-width="120px">
        <el-form-item label="监控品种">
          <el-input value="Au(T+D)" disabled />
        </el-form-item>
        <el-form-item label="轮询间隔(秒)">
          <el-input-number :min="5" :max="300" :value="10" />
        </el-form-item>
        <el-form-item label="数据保留(天)">
          <el-input-number :min="30" :max="365" :value="90" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="setting-card">
      <template #header><span>通知配置</span></template>
      <el-form label-width="120px">
        <el-form-item label="启用通知">
          <el-switch :value="true" />
        </el-form-item>
        <el-form-item label="价格变化阈值">
          <el-input-number :min="0.1" :max="10" :precision="1" :value="1.0" />
          <span class="unit">%</span>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { library } from '@fortawesome/fontawesome-svg-core'
import { faCog } from '@fortawesome/free-solid-svg-icons'

library.add(faCog)
</script>

<style lang="scss" scoped>
.settings {
  max-width: 700px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }
}

.setting-card {
  margin-bottom: 20px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .unit {
    margin-left: 8px;
    color: var(--text-secondary);
  }
}
</style>
