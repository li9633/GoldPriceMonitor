<template>
  <div v-loading="group.loading" class="tab-content">
    <el-form v-if="group.data" label-width="180px" class="settings-form">
      <el-form-item label="启用建议">
        <el-switch v-model="group.data.enabled" />
        <div class="hint">关闭后监控循环不再评估与推送建议</div>
      </el-form-item>

      <el-form-item label="计划买入总资金">
        <el-input-number v-model="group.data.total_investable" :min="0" :step="10000" />
        <span class="unit">元</span>
        <div class="hint">用于算出「这次该买多少克」；填 0 表示不设上限</div>
      </el-form-item>

      <el-form-item label="目标持仓克数">
        <el-input-number v-model="group.data.target_grams" :min="0" :step="10" :precision="2" />
        <span class="unit">克</span>
        <div class="hint">与总资金同时填写时，取更紧的那个约束</div>
      </el-form-item>

      <el-form-item label="目标持仓占比">
        <el-input-number v-model="group.data.target_position_ratio" :min="0" :max="100" :step="5" />
        <span class="unit">%</span>
      </el-form-item>

      <el-form-item label="风险偏好">
        <el-select v-model="group.data.risk_level" class="narrow-select">
          <el-option value="conservative" label="保守" />
          <el-option value="balanced" label="均衡" />
          <el-option value="aggressive" label="进取" />
        </el-select>
      </el-form-item>

      <el-form-item label="用 AI 润色措辞">
        <el-switch v-model="group.data.enable_llm" />
        <div class="hint">
          只影响文字表达，不影响动作、克数和价位（那些由规则计算）。AI 不可用时自动回退到规则措辞
        </div>
      </el-form-item>

      <el-form-item label="重复推送价格阈值">
        <el-input-number
          v-model="group.data.price_move_trigger_pct"
          :min="0"
          :max="10"
          :step="0.1"
          :precision="1"
        />
        <span class="unit">%</span>
        <div class="hint">
          建议动作没变、且价格偏离上次推送不足该比例时，不重复推送。填 0 表示只在动作变化时推送
        </div>
      </el-form-item>

      <el-form-item class="form-actions">
        <el-button type="primary" :loading="group.saving" @click="group.save()">
          保存建议配置
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { adviceApi } from '@/api/modules/advice'
import { useSettingsGroup } from '@/composables/useSettings'

const group = useSettingsGroup(
  () => adviceApi.getConfig(),
  (data) => adviceApi.updateConfig(data)
)

onMounted(() => group.load())
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .narrow-select {
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

  .hint {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.6;
    margin-top: 4px;
  }
}
</style>
