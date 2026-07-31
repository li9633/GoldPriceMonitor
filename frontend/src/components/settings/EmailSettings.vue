<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-form-item label="启用邮件通知">
        <el-switch v-model="group.data.enabled" />
      </el-form-item>
      <el-form-item label="SMTP 服务器">
        <el-input v-model="group.data.smtp_server" placeholder="smtp.qq.com" />
      </el-form-item>
      <el-form-item label="SMTP 端口">
        <el-input-number v-model="group.data.smtp_port" :min="1" :max="65535" />
      </el-form-item>
      <el-form-item label="发件邮箱">
        <el-input v-model="group.data.sender_email" placeholder="your@email.com" />
      </el-form-item>
      <el-form-item label="发件密码">
        <el-input
          v-model="group.data.sender_password"
          type="password"
          show-password
          placeholder="授权码或密码"
        />
      </el-form-item>
      <el-form-item label="收件邮箱">
        <el-input v-model="group.data.receiver_email" placeholder="receiver@email.com" />
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存邮件配置
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
  () => settingsApi.getEmail(),
  (data) => settingsApi.updateEmail(data),
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
