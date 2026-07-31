<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <el-form-item label="检查间隔">
        <el-input-number v-model="group.data.check_interval" :min="1" :max="3600" />
        <span class="unit">秒</span>
      </el-form-item>
      <el-form-item label="主监控品种">
        <el-input v-model="group.data.main_symbol" placeholder="gds_AUTD" />
      </el-form-item>
      <el-form-item label="监控品种列表">
        <el-select
          v-model="group.data.monitor_symbols"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="输入品种代码并回车添加"
          class="full-width-select"
        >
          <el-option v-for="s in group.data.monitor_symbols" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item label="交易时段">
        <div class="trading-hours">
          <div v-for="(slot, index) in group.data.trading_hours" :key="index" class="trading-slot">
            <el-time-picker
              v-model="slot[0]"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="开始"
            />
            <span class="slot-sep">—</span>
            <el-time-picker
              v-model="slot[1]"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="结束"
            />
            <el-button
              text
              type="danger"
              size="small"
              @click="group.data.trading_hours.splice(index, 1)"
            >
              <font-awesome-icon icon="times" />
            </el-button>
          </div>
          <el-button
            text
            type="primary"
            size="small"
            @click="group.data.trading_hours.push(['09:00', '11:30'])"
          >
            <font-awesome-icon icon="plus" /> 添加时段
          </el-button>
        </div>
      </el-form-item>
      <el-form-item label="盎司转克常数">
        <el-input-number
          v-model="group.data.ounce_to_gram"
          :precision="4"
          :step="0.0001"
          disabled
        />
        <span class="unit">克/盎司（只读）</span>
      </el-form-item>
      <el-form-item label="启动时自动导入">
        <el-switch v-model="group.data.auto_import_on_start" />
      </el-form-item>
      <el-form-item label="最小记录阈值">
        <el-input-number v-model="group.data.min_records_threshold" :min="10" :max="10000" />
        <span class="unit">条</span>
      </el-form-item>
      <el-form-item label="监控周期">
        <el-checkbox-group v-model="group.data.periods">
          <el-checkbox value="60d" label="60天" />
          <el-checkbox value="1y" label="1年" />
          <el-checkbox value="30d" label="30天" />
          <el-checkbox value="7d" label="7天" />
        </el-checkbox-group>
      </el-form-item>
      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存监控配置
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faPlus, faTimes } from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import { useSettingsGroup } from '@/composables/useSettings'

library.add(faPlus, faTimes)

const group = useSettingsGroup(
  () => settingsApi.getMonitor(),
  (data) => settingsApi.updateMonitor(data),
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .full-width-select {
    width: 100%;
  }

  .trading-hours {
    .trading-slot {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;

      .slot-sep {
        color: var(--text-secondary);
        font-size: 14px;
      }
    }
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
