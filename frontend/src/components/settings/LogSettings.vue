<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="最大文件大小、备份文件数量、压缩旧日志、控制台输出 修改后需重启服务生效"
        class="log-notice"
      />
      <el-form-item label="最大文件大小">
        <el-input-number v-model="group.data.max_bytes" :min="1048576" :step="1048576" />
        <span class="unit">字节 ({{ (group.data.max_bytes / 1048576).toFixed(1) }} MB)</span>
      </el-form-item>
      <el-form-item label="备份文件数量">
        <el-input-number v-model="group.data.backup_count" :min="1" :max="100" />
      </el-form-item>
      <el-form-item label="压缩旧日志">
        <el-switch v-model="group.data.compress_backup" />
      </el-form-item>
      <el-form-item label="控制台输出">
        <el-switch v-model="group.data.console_output" />
      </el-form-item>
      <el-form-item label="保留天数">
        <el-input-number v-model="group.data.keep_days" :min="1" :max="365" />
        <span class="unit">天（运行时生效）</span>
      </el-form-item>
      <el-form-item label="日志等级">
        <el-select v-model="group.data.log_level" class="log-level-select">
          <el-option value="DEBUG" label="DEBUG — 全部日志（默认，开发调试用）" />
          <el-option value="INFO" label="INFO — 一般信息 + 警告 + 错误" />
          <el-option value="WARNING" label="WARNING — 仅警告 + 错误" />
          <el-option value="ERROR" label="ERROR — 仅错误" />
        </el-select>
        <span class="unit">即时生效，无需重启</span>
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存日志配置
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
  () => settingsApi.getLog(),
  (data) => settingsApi.updateLog(data),
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;

  .log-notice {
    margin-bottom: 20px;
  }
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
