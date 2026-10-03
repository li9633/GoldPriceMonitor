<template>
  <div v-loading="group.loading || positionLoading" class="tab-content">
    <!-- 持仓是建议的前提：没有它，系统给不出「补仓还是卖出」。放在最上面，避免用户到处找。 -->
    <el-card shadow="never" class="position-card">
      <template #header>
        <div class="position-header">
          <span class="position-title">我的当前持仓</span>
          <el-button v-if="position" text type="primary" @click="openOpeningDialog()">
            调整持仓
          </el-button>
        </div>
      </template>

      <div v-if="position" class="position-body">
        <div class="position-metric">
          <span class="metric-label">持有</span>
          <span class="metric-value">{{ position.total_grams }} g</span>
        </div>
        <div class="position-metric">
          <span class="metric-label">成本价</span>
          <span class="metric-value">¥{{ formatPrice(position.avg_cost) }}/克</span>
        </div>
        <div class="position-metric">
          <span class="metric-label">浮动盈亏</span>
          <span class="metric-value" :class="pnlClass">
            <template v-if="position.unrealized_pnl_pct !== null">
              {{ formatChangePercent(position.unrealized_pnl_pct) }}
            </template>
            <template v-else>—</template>
          </span>
        </div>
        <div class="position-actions">
          <el-button link type="primary" @click="router.push('/portfolio')">
            查看与编辑每一笔买入 →
          </el-button>
        </div>
      </div>

      <div v-else-if="!positionLoading" class="position-empty">
        <p class="empty-text">
          还没有录入持仓。录入后系统才能判断该补仓、持有还是止盈止损 ——
          否则只会给出「该不该买」的建议。
        </p>
        <el-button type="primary" @click="openOpeningDialog()">录入我的持仓</el-button>
        <p class="empty-hint">
          只需要填<strong>总克数</strong>和<strong>平均成本价</strong>；
          没在系统里记过每一笔买入也能用。
        </p>
      </div>
    </el-card>

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
        <div class="hint">
          持仓市值占总资金超过该比例时提醒「仓位偏重」；填 0 表示用默认上限 100%
        </div>
      </el-form-item>

      <el-form-item label="风险偏好">
        <el-select v-model="group.data.risk_level" class="narrow-select">
          <el-option value="conservative" label="保守" />
          <el-option value="balanced" label="均衡" />
          <el-option value="aggressive" label="进取" />
        </el-select>
        <div class="hint">
          决定三件事：<strong>止盈/止损/浮亏提醒的触发点位</strong>、<strong>每次买入的比例</strong>、
          以及<strong>止盈止损时的卖出力度</strong>。当前档位：
          {{ riskDescription }}
        </div>
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

    <LotFormDialog
      v-model="openingDialogVisible"
      mode="opening"
      :symbols="symbols"
      :default-symbol="defaultSymbol"
      @saved="loadPosition"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { adviceApi } from '@/api/modules/advice'
import { portfolioApi } from '@/api/modules/portfolio'
import type { PositionSummary } from '@/api/modules/portfolio'
import { useSettingsGroup } from '@/composables/useSettings'
import { formatChangePercent, formatPrice } from '@/utils/format'
import LotFormDialog from '@/components/LotFormDialog.vue'

const router = useRouter()

const group = useSettingsGroup(
  () => adviceApi.getConfig(),
  (data) => adviceApi.updateConfig(data)
)

const position = ref<PositionSummary | null>(null)
const positionLoading = ref(false)
const openingDialogVisible = ref(false)
/** 录入持仓时可选的品种：优先用监控里的品种 */
const symbols = ref<string[]>([])
const defaultSymbol = ref('')

const pnlClass = computed(() => {
  const value = position.value?.unrealized_pnl_pct
  if (value === null || value === undefined) return ''
  return value >= 0 ? 'is-up' : 'is-down'
})

/** 把档位说清楚 —— 用户选了「保守」应该知道到底变了什么 */
const DEFAULT_RISK_DESCRIPTION =
  '浮盈 +8% 提示止盈、浮亏 -3% 提示补仓、-10% 考虑止损；按计划比例买入'

const RISK_DESCRIPTIONS: Record<string, string> = {
  conservative: '浮盈 +5% 就提示止盈、浮亏 -2% 提示补仓、-6% 考虑止损；每次买得更少',
  balanced: DEFAULT_RISK_DESCRIPTION,
  aggressive: '浮盈 +12% 才提示止盈、浮亏 -5% 才提示补仓、-15% 才考虑止损；每次买得更多'
}

const riskDescription = computed(
  () => RISK_DESCRIPTIONS[group.data?.risk_level ?? 'balanced'] ?? DEFAULT_RISK_DESCRIPTION
)

async function loadPosition() {
  positionLoading.value = true
  try {
    const summary = await portfolioApi.getSummary()
    // 必须挑「还有持仓」的那一个，不能直接取 positions[0]：
    // 全部卖光的品种也会出现在列表里（保留它的已实现盈亏），
    // 万一它排在前面，界面就会谎称「还没有录入持仓」。
    const held = summary.positions.find((item) => item.total_grams > 0) ?? null
    position.value = held
    defaultSymbol.value = held?.symbol ?? summary.plans[0]?.symbol ?? ''
  } catch {
    // 错误提示已由 request 拦截器统一处理
  } finally {
    positionLoading.value = false
  }
}

async function loadSymbols() {
  // 持仓品种来自计划与已有记录；这里只做一个尽量友好的候选列表
  try {
    const summary = await portfolioApi.getSummary()
    const seen = new Set<string>()
    for (const item of [...summary.positions, ...summary.plans]) {
      if (item.symbol) seen.add(item.symbol)
    }
    symbols.value = [...seen]
    const firstSymbol = symbols.value[0]
    if (!defaultSymbol.value && firstSymbol) {
      defaultSymbol.value = firstSymbol
    }
  } catch {
    // 忽略：候选为空也能手输
  }
}

function openOpeningDialog() {
  openingDialogVisible.value = true
}

onMounted(async () => {
  await Promise.all([group.load(), loadPosition(), loadSymbols()])
})
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.position-card {
  margin-bottom: 20px;
  border-color: var(--border-color);

  .position-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .position-title {
    font-weight: 600;
  }

  .position-body {
    display: flex;
    align-items: center;
    gap: 32px;
    flex-wrap: wrap;
  }

  .position-metric {
    display: flex;
    flex-direction: column;
    gap: 4px;

    .metric-label {
      font-size: 12px;
      color: var(--text-muted);
    }

    .metric-value {
      font-size: 18px;
      font-weight: 600;

      &.is-up {
        color: var(--price-up);
      }

      &.is-down {
        color: var(--price-down);
      }
    }
  }

  .position-actions {
    margin-left: auto;
  }

  .position-empty {
    .empty-text {
      margin: 0 0 12px;
      color: var(--text-secondary);
      line-height: 1.7;
    }

    .empty-hint {
      margin: 12px 0 0;
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.6;
    }
  }
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
