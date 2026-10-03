<template>
  <el-card class="advice-card" shadow="hover">
    <template #header>
      <div class="advice-header">
        <span class="advice-title"> <font-awesome-icon icon="lightbulb" /> {{ title }} </span>
        <div class="advice-meta">
          <el-tag size="small" effect="plain">{{ kindLabel }}</el-tag>
          <el-tag size="small" :type="statusTagType">{{ statusLabel }}</el-tag>
          <span class="advice-time">{{ advice.created_at }}</span>
        </div>
      </div>
    </template>

    <div class="advice-body">
      <div class="action-row">
        <el-tag :type="actionTagType" size="large" effect="dark">
          {{ actionLabel }}
        </el-tag>
        <div class="action-numbers">
          <div class="number-item">
            <span class="label">建议数量</span>
            <span class="value">{{ targetGramsText }}</span>
          </div>
          <div class="number-item">
            <span class="label">建议价位</span>
            <span class="value">{{ priceBandText }}</span>
          </div>
          <div class="number-item">
            <span class="label">置信度</span>
            <span class="value">{{ (advice.confidence * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>

      <p v-if="advice.rationale" class="rationale">{{ advice.rationale }}</p>

      <el-alert
        v-if="advice.status === 'suppressed'"
        class="suppressed-alert"
        type="info"
        :closable="false"
        show-icon
        :title="suppressedText"
      />

      <div class="section">
        <div class="section-toggle" @click="showSignals = !showSignals">
          <font-awesome-icon :icon="showSignals ? 'chevron-down' : 'chevron-right'" />
          判断依据（{{ advice.signals.length }}）
        </div>
        <ul v-show="showSignals" class="signal-list">
          <li
            v-for="signal in advice.signals"
            :key="signal.id"
            :class="`severity-${signal.severity}`"
          >
            {{ signal.summary }}
          </li>
        </ul>
      </div>

      <div v-if="rows.length" class="section">
        <div class="section-toggle" @click="showEvidence = !showEvidence">
          <font-awesome-icon :icon="showEvidence ? 'chevron-down' : 'chevron-right'" />
          当时的行情与持仓（可回溯）
        </div>
        <div v-show="showEvidence" class="evidence-grid">
          <div v-for="row in rows" :key="row.label" class="evidence-item">
            <span class="label">{{ row.label }}</span>
            <span class="value">{{ row.value }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="advice-footer">
      <span class="model-info">
        {{ advice.model_info ? `措辞模型：${advice.model_info}` : '规则生成（未使用 AI 措辞）' }}
      </span>
      <div v-if="showActions" class="footer-actions">
        <el-button
          v-if="suggestsSell"
          size="small"
          type="primary"
          @click="saleDialogVisible = true"
        >
          <font-awesome-icon icon="check" /> 记录这笔卖出
        </el-button>
        <el-button
          v-if="advice.status === 'delivered'"
          text
          size="small"
          :loading="busy"
          @click="acknowledge"
        >
          标记已读
        </el-button>
        <el-button
          v-if="advice.status !== 'acted'"
          text
          size="small"
          type="primary"
          :loading="busy"
          @click="markActed"
        >
          我照做了
        </el-button>
        <el-button text size="small" @click="emit('refresh')">
          <font-awesome-icon icon="rotate" /> 重新生成
        </el-button>
      </div>
    </div>

    <SaleFormDialog
      v-model="saleDialogVisible"
      :default-symbol="advice.symbol"
      :default-grams="advice.target_grams"
      :default-price="positionPrice"
      :symbols="[advice.symbol]"
      :available-grams="positionGrams"
      :available-avg-cost="positionAvgCost"
      @saved="onSaleSaved"
    />
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faCheck,
  faChevronDown,
  faChevronRight,
  faLightbulb,
  faRotate
} from '@fortawesome/free-solid-svg-icons'
import { adviceApi } from '@/api/modules/advice'
import type { AdviceRecord } from '@/api/modules/advice'
import SaleFormDialog from '@/components/SaleFormDialog.vue'
import {
  ACTION_LABELS,
  ACTION_TAG_TYPES,
  KIND_LABELS,
  STATUS_LABELS,
  STATUS_TAG_TYPES,
  SUPPRESSED_REASON_LABELS,
  evidenceRows
} from '@/utils/adviceHelpers'

library.add(faCheck, faChevronDown, faChevronRight, faLightbulb, faRotate)

const props = withDefaults(
  defineProps<{
    advice: AdviceRecord
    title?: string
    showActions?: boolean
  }>(),
  {
    title: '当前建议',
    showActions: true
  }
)

const emit = defineEmits<{
  refresh: []
  changed: []
}>()

const showSignals = ref(true)
const showEvidence = ref(false)
const busy = ref(false)
const saleDialogVisible = ref(false)

/** 建议里带减仓动作时，直接给一个「记录这笔卖出」的入口 */
const SELL_ACTIONS = new Set(['TAKE_PROFIT', 'STOP_LOSS'])
const suggestsSell = computed(
  () => SELL_ACTIONS.has(props.advice.action) && (props.advice.target_grams ?? 0) > 0
)

/** 从冻结的 evidence 里取持仓口径 —— 与生成建议时看到的完全一致 */
const positionEvidence = computed<Record<string, unknown>>(() => {
  const raw = props.advice.evidence
  if (!raw || typeof raw !== 'object') return {}
  const position = (raw as Record<string, unknown>).position
  return position && typeof position === 'object' ? (position as Record<string, unknown>) : {}
})

const positionGrams = computed(() => {
  const value = positionEvidence.value.total_grams
  return typeof value === 'number' ? value : null
})

const positionAvgCost = computed(() => {
  const value = positionEvidence.value.avg_cost
  return typeof value === 'number' ? value : null
})

/** 卖出价默认填「建议价区间的中间价」，取自建议本身 */
const positionPrice = computed(() => {
  const { price_band_low: low, price_band_high: high } = props.advice
  if (low === null || high === null) return null
  return Number(((low + high) / 2).toFixed(2))
})

function onSaleSaved() {
  ElMessage.success('已记录卖出，持仓已更新')
  emit('changed')
}

const actionLabel = computed(() => ACTION_LABELS[props.advice.action] ?? props.advice.action)
const actionTagType = computed(() => ACTION_TAG_TYPES[props.advice.action] ?? 'info')
const kindLabel = computed(() => KIND_LABELS[props.advice.kind] ?? props.advice.kind)
const statusLabel = computed(() => STATUS_LABELS[props.advice.status] ?? props.advice.status)
const statusTagType = computed(() => STATUS_TAG_TYPES[props.advice.status] ?? 'info')

const targetGramsText = computed(() =>
  props.advice.target_grams ? `${props.advice.target_grams} g` : '—（本次不涉及数量）'
)

const priceBandText = computed(() => {
  const { price_band_low: low, price_band_high: high } = props.advice
  if (low === null || high === null) return '—'
  return `¥${low.toFixed(2)} ~ ¥${high.toFixed(2)}`
})

const suppressedText = computed(() => {
  const reason = props.advice.suppressed_reason
  return SUPPRESSED_REASON_LABELS[reason] ?? `未推送（${reason || '原因未知'}）`
})

const rows = computed(() => evidenceRows(props.advice.evidence))

async function acknowledge() {
  busy.value = true
  try {
    await adviceApi.acknowledge(props.advice.id)
    ElMessage.success('已标记为已读')
    emit('changed')
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function markActed() {
  busy.value = true
  try {
    await adviceApi.markActed(props.advice.id)
    ElMessage.success('已记录为已执行，可用于评估建议有效性')
    emit('changed')
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
.advice-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  margin-bottom: 20px;

  .advice-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .advice-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .advice-meta {
    display: flex;
    align-items: center;
    gap: 8px;

    .advice-time {
      font-size: 12px;
      color: var(--text-muted);
    }
  }

  .action-row {
    display: flex;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
    margin-bottom: 14px;
  }

  .action-numbers {
    display: flex;
    gap: 24px;
    flex-wrap: wrap;

    .number-item {
      display: flex;
      flex-direction: column;

      .label {
        font-size: 12px;
        color: var(--text-muted);
      }

      .value {
        font-size: 15px;
        font-weight: 600;
        color: var(--text-primary);
      }
    }
  }

  .rationale {
    font-size: 14px;
    line-height: 1.75;
    color: var(--text-secondary);
    margin: 0 0 14px 0;
    white-space: pre-wrap;
  }

  .suppressed-alert {
    margin-bottom: 14px;
  }

  .section {
    margin-bottom: 10px;

    .section-toggle {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--text-muted);
      cursor: pointer;
      user-select: none;

      &:hover {
        color: var(--text-primary);
      }
    }
  }

  .signal-list {
    margin: 8px 0 0 0;
    padding-left: 18px;
    font-size: 13px;
    line-height: 1.9;
    color: var(--text-secondary);

    li.severity-critical {
      color: var(--price-down);
    }

    li.severity-warning {
      color: var(--price-up);
    }

    li.severity-notice {
      color: var(--text-primary);
    }
  }

  .evidence-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 6px 16px;
    margin-top: 10px;
    font-size: 13px;

    .evidence-item {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      border-bottom: 1px dashed var(--border-color);
      padding-bottom: 4px;

      .label {
        color: var(--text-muted);
      }

      .value {
        color: var(--text-primary);
      }
    }
  }

  .advice-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 8px;
    padding-top: 12px;
    border-top: 1px solid var(--border-color);

    .model-info {
      font-size: 12px;
      color: var(--text-muted);
    }
  }
}
</style>
