<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-form-item label="包含时间">
        <el-switch v-model="group.data.include_time" />
      </el-form-item>
      <el-form-item label="价格格式">
        <el-input v-model="group.data.price_format" placeholder="¥{:.2f}" />
      </el-form-item>
      <el-form-item label="最大条件数">
        <el-input-number v-model="group.data.max_conditions" :min="1" :max="20" />
      </el-form-item>
      <el-form-item label="启用建议">
        <el-switch v-model="group.data.enable_suggestions" />
      </el-form-item>
      <el-form-item label="建议级别">
        <el-select v-model="group.data.suggestion_level" :disabled="!group.data.enable_suggestions">
          <el-option value="low" label="低" />
          <el-option value="medium" label="中" />
          <el-option value="high" label="高" />
        </el-select>
      </el-form-item>
      <el-form-item label="包含止损建议">
        <el-switch v-model="group.data.include_stop_loss" />
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存消息模板
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
  () => settingsApi.getMessage(),
  (data) => settingsApi.updateMessage(data),
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .form-actions {
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
  }
}
</style>
