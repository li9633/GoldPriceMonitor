<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="160px" class="settings-form">
      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="bell" /> 绝对价格报警</h4>
        <el-form-item label="启用绝对价格报警">
          <el-switch v-model="group.data.enable_absolute_alert" />
        </el-form-item>
        <el-form-item label="绝对低价阈值">
          <el-input-number
            v-model="group.data.absolute_low_price"
            :min="0"
            :precision="1"
            :disabled="!group.data.enable_absolute_alert"
          />
          <span class="unit">¥</span>
        </el-form-item>
      </div>

      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="clock" /> 相对价格报警</h4>
        <el-form-item label="启用相对价格报警">
          <el-switch v-model="group.data.enable_relative_alert" />
        </el-form-item>
        <el-form-item label="相对窗口时长">
          <el-input-number
            v-model="group.data.relative_window_hours"
            :min="1"
            :max="720"
            :disabled="!group.data.enable_relative_alert"
          />
          <span class="unit">小时</span>
        </el-form-item>
      </div>

      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="arrow-trend-up" /> 突破报警</h4>
        <el-form-item label="启用突破报警">
          <el-switch v-model="group.data.enable_breakout_alert" />
        </el-form-item>
        <el-form-item label="盘整时长">
          <el-input-number
            v-model="group.data.consolidation_hours"
            :min="1"
            :max="720"
            :disabled="!group.data.enable_breakout_alert"
          />
          <span class="unit">小时</span>
        </el-form-item>
        <el-form-item label="波动率阈值">
          <el-input-number
            v-model="group.data.volatility_threshold"
            :min="0.001"
            :max="0.1"
            :precision="3"
            :step="0.001"
            :disabled="!group.data.enable_breakout_alert"
          />
          <span class="unit">(小数)</span>
        </el-form-item>
      </div>

      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="wave-square" /> 技术指标报警</h4>
        <el-form-item label="启用趋势报警">
          <el-switch v-model="group.data.enable_trend_alert" />
        </el-form-item>
        <el-form-item label="启用波动率报警">
          <el-switch v-model="group.data.enable_volatility_alert" />
        </el-form-item>
        <el-form-item label="启用均线交叉报警">
          <el-switch v-model="group.data.enable_ma_cross_alert" />
        </el-form-item>
        <el-form-item label="短期均线周期">
          <el-input-number
            v-model="group.data.ma_short_period"
            :min="2"
            :max="200"
            :disabled="!group.data.enable_ma_cross_alert"
          />
        </el-form-item>
        <el-form-item label="长期均线周期">
          <el-input-number
            v-model="group.data.ma_long_period"
            :min="5"
            :max="500"
            :disabled="!group.data.enable_ma_cross_alert"
          />
        </el-form-item>
      </div>

      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="bolt" /> 快速变化报警</h4>
        <el-form-item label="启用连续变化报警">
          <el-switch v-model="group.data.enable_consecutive_alert" />
        </el-form-item>
        <el-form-item label="连续变化次数">
          <el-input-number
            v-model="group.data.consecutive_count"
            :min="2"
            :max="50"
            :disabled="!group.data.enable_consecutive_alert"
          />
          <span class="unit">次</span>
        </el-form-item>
        <el-form-item label="启用快速变化报警">
          <el-switch v-model="group.data.enable_rapid_change_alert" />
        </el-form-item>
        <el-form-item label="快速变化阈值">
          <el-input-number
            v-model="group.data.rapid_change_threshold"
            :min="0.001"
            :max="0.5"
            :precision="3"
            :step="0.001"
            :disabled="!group.data.enable_rapid_change_alert"
          />
          <span class="unit">(小数)</span>
        </el-form-item>
        <el-form-item label="快速变化窗口">
          <el-input-number
            v-model="group.data.rapid_change_window_minutes"
            :min="1"
            :max="1440"
            :disabled="!group.data.enable_rapid_change_alert"
          />
          <span class="unit">分钟</span>
        </el-form-item>
      </div>

      <div class="form-section">
        <h4 class="section-title"><font-awesome-icon icon="angle-double-down" /> 长期低位报警</h4>
        <el-form-item label="启用长期低位报警">
          <el-switch v-model="group.data.enable_long_term_low_alert" />
        </el-form-item>
      </div>

      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存报警配置
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faBell,
  faClock,
  faArrowTrendUp,
  faWaveSquare,
  faBolt,
  faAngleDoubleDown,
} from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import { useSettingsGroup } from '@/composables/useSettings'

library.add(faBell, faClock, faArrowTrendUp, faWaveSquare, faBolt, faAngleDoubleDown)

const group = useSettingsGroup(
  () => settingsApi.getAlert(),
  (data) => settingsApi.updateAlert(data),
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .form-section {
    margin-bottom: 24px;
    padding: 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--border-color);

    .section-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
      margin: 0 0 16px 0;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border-color);
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
