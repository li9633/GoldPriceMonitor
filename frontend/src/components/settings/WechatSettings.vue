<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-form-item label="启用企业微信通知">
        <el-switch v-model="group.data.enabled" />
      </el-form-item>
      <el-form-item label="Webhook 地址">
        <el-input
          v-model="group.data.webhook_url"
          type="textarea"
          :rows="3"
          placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
        />
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存企业微信配置
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
  () => settingsApi.getWeChat(),
  (data) => settingsApi.updateWeChat(data),
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
