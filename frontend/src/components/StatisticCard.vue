<template>
  <el-card class="statistic-card" shadow="hover">
    <div class="statistic-header">
      <span class="statistic-label">{{ label }}</span>
      <el-tooltip
        v-if="canAbbreviate && !isExternallyControlled"
        :content="currentAbbreviated ? '显示完整数字' : '缩略显示'"
        placement="top"
      >
        <span class="toggle-btn" @click.stop="toggle">
          <font-awesome-icon :icon="currentAbbreviated ? faExpand : faCompress" />
        </span>
      </el-tooltip>
    </div>
    <div v-if="formatter" class="statistic-value" :class="{ 'price-color': highlight }">
      {{ formatter(value, formatContext) }}
    </div>
    <el-statistic
      v-else-if="isNumeric"
      :value="displayValue"
      :precision="displayPrecision"
      :prefix="prefix"
      :suffix="displaySuffix"
      :value-style="computedValueStyle"
    />
    <div v-else class="statistic-value" :class="{ 'price-color': highlight }">
      {{ value }}
    </div>
    <div v-if="sub" class="statistic-sub" :class="subClass">{{ sub }}</div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faExpand, faCompress } from '@fortawesome/free-solid-svg-icons'

library.add(faExpand, faCompress)

type FormatPreset = 'number' | 'integer' | 'percent' | 'bytes' | 'raw'

interface FormatContext {
  numericValue: number
  rawValue: number | string | undefined
  abbreviated: boolean
}

const props = withDefaults(
  defineProps<{
    label: string
    value?: number | string
    format?: FormatPreset
    formatter?: (value: number | string | undefined, ctx: FormatContext) => string
    prefix?: string
    suffix?: string
    precision?: number
    sub?: string
    subClass?: string
    highlight?: boolean
    abbreviated?: boolean
  }>(),
  {
    value: undefined,
    format: 'number',
    prefix: '',
    suffix: '',
    precision: undefined,
    sub: undefined,
    subClass: undefined,
    highlight: false,
    abbreviated: undefined,
  },
)

const emit = defineEmits<{
  'update:abbreviated': [value: boolean]
}>()

const isExternallyControlled = computed(() => props.abbreviated !== undefined)

const internalAbbreviated = ref(false)

const currentAbbreviated = computed(() =>
  isExternallyControlled.value ? props.abbreviated! : internalAbbreviated.value,
)

function toggle() {
  if (isExternallyControlled.value) {
    emit('update:abbreviated', !props.abbreviated)
  } else {
    internalAbbreviated.value = !internalAbbreviated.value
  }
}

const formatContext = computed<FormatContext>(() => ({
  numericValue: numericValue.value,
  rawValue: props.value,
  abbreviated: currentAbbreviated.value,
}))

// -- 数值解析（仅接受纯数字格式，排除带 % / 单位等后缀的字符串） --
const numericValue = computed(() => {
  const v = props.value
  if (v == null) return NaN
  if (typeof v === 'number') return v
  const trimmed = v.trim()
  if (/^-?[\d,]+(\.\d+)?$/.test(trimmed)) {
    return parseFloat(trimmed.replace(/,/g, ''))
  }
  return NaN
})

const isNumeric = computed(() => !isNaN(numericValue.value))

// 是否可缩略（根据 format 预设决定阈值）
const canAbbreviate = computed(() => {
  if (!isNumeric.value) return false
  if (props.format === 'percent' || props.format === 'raw') return false
  if (props.format === 'bytes') return Math.abs(numericValue.value) >= 1024
  return Math.abs(numericValue.value) >= 10_000
})

// 值变小后自动切回完整模式（仅内部状态）
watch(canAbbreviate, (can) => {
  if (!can && !isExternallyControlled.value) internalAbbreviated.value = false
})

// -- 缩略信息 --
const abbrInfo = computed(() => {
  if (!isNumeric.value || !currentAbbreviated.value) return null
  const num = numericValue.value
  if (props.format === 'bytes') {
    const abs = Math.abs(num)
    if (abs >= 1e12) return { value: num / 1e12, unit: 'TB' }
    if (abs >= 1e9) return { value: num / 1e9, unit: 'GB' }
    if (abs >= 1e6) return { value: num / 1e6, unit: 'MB' }
    if (abs >= 1024) return { value: num / 1024, unit: 'KB' }
    return null
  }
  if (Math.abs(num) >= 1e8) return { value: num / 1e8, unit: '亿' }
  if (Math.abs(num) >= 1e4) return { value: num / 1e4, unit: '万' }
  return null
})

const displayValue = computed(() => abbrInfo.value?.value ?? numericValue.value)

const displaySuffix = computed(() => {
  const unit = abbrInfo.value?.unit ?? ''
  return unit + (props.suffix ?? '')
})

const displayPrecision = computed(() => {
  if (props.precision != null) return props.precision
  if (props.format === 'integer') return 0
  if (props.format === 'percent') return 1
  if (!abbrInfo.value) return 0
  return Number.isInteger(abbrInfo.value.value) ? 0 : 1
})

// -- 样式 --
const computedValueStyle = computed(() => {
  return {
    fontSize: '28px',
    fontWeight: 'bold',
    color: props.highlight ? 'var(--price-color)' : 'var(--text-primary)',
  }
})
</script>

<style lang="scss" scoped>
.statistic-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  transition:
    transform 0.2s,
    background 0.3s;

  &:hover {
    transform: translateY(-2px);
  }

  .statistic-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }

  .statistic-label {
    font-size: 13px;
    color: var(--text-secondary);
  }

  .toggle-btn {
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 13px;
    padding: 2px 4px;
    border-radius: 4px;
    transition: color 0.2s;

    &:hover {
      color: var(--color-primary);
    }
  }

  .statistic-value {
    font-size: 28px;
    font-weight: bold;
    color: var(--text-primary);

    &.price-color {
      color: var(--price-color);
    }
  }

  .statistic-sub {
    font-size: 13px;
    margin-top: 6px;

    &.up {
      color: var(--price-up);
    }
    &.down {
      color: var(--price-down);
    }
    &.stable {
      color: var(--text-muted);
    }
  }
}

// 覆盖 el-statistic 默认样式，使其融入卡片
:deep(.el-statistic) {
  .el-statistic__head {
    display: none; // 隐藏 el-statistic 自带的 title，我们用自定义 header
  }

  .el-statistic__content {
    margin-top: 0;
  }

  .el-statistic__number {
    font-size: 28px;
    font-weight: bold;
  }

  .el-statistic__prefix,
  .el-statistic__suffix {
    font-size: 16px;
    font-weight: 500;
  }
}
</style>
