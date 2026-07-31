<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-form-item label="启用 AI">
        <el-switch v-model="group.data.enabled" />
      </el-form-item>
      <el-form-item label="启用 Prompt 检查">
        <el-switch v-model="group.data.prompt_check" />
      </el-form-item>
      <el-form-item label="Temperature">
        <el-input-number
          v-model="group.data.temperature"
          :min="0"
          :max="2"
          :precision="1"
          :step="0.1"
        />
      </el-form-item>
      <el-form-item label="Max Tokens">
        <el-input-number v-model="group.data.max_tokens" :min="256" :max="32768" :step="256" />
      </el-form-item>
      <el-form-item label="检查间隔">
        <el-select v-model="group.data.check_interval_minutes" class="log-level-select">
          <el-option :value="1" label="1 分钟" />
          <el-option :value="5" label="5 分钟" />
          <el-option :value="10" label="10 分钟" />
          <el-option :value="15" label="15 分钟" />
          <el-option :value="30" label="30 分钟" />
        </el-select>
        <span class="unit">重启后首次立即分析，之后按间隔执行</span>
      </el-form-item>
      <el-form-item label="最大重试次数">
        <el-input-number v-model="group.data.max_retries" :min="0" :max="10" />
      </el-form-item>
      <el-form-item label="重试基础延迟">
        <el-input-number
          v-model="group.data.retry_base_delay"
          :min="0.1"
          :max="60"
          :precision="1"
          :step="0.5"
        />
        <span class="unit">秒</span>
      </el-form-item>
      <el-form-item label="缓存 TTL">
        <el-input-number v-model="group.data.cache_ttl_minutes" :min="1" :max="1440" />
        <span class="unit">分钟</span>
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存 AI 配置
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { settingsApi } from '@/api/modules/settings'
import { useSettingsGroup } from '@/composables/useSettings'

const group = useSettingsGroup(
  () => settingsApi.getAI(),
  (data) => settingsApi.updateAI(data),
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .log-level-select {
    width: 220px;
  }

  .form-actions {
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
  }

  .unit {
    margin-left: 8px;
    color: var(--text-secondary);
    font-size: 13px;
  }
}
</style>
