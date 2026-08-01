<template>
  <div class="time-range-filter">
    <span class="filter-label"><font-awesome-icon icon="calendar" /> 时间范围</span>
    <el-radio-group :model-value="modelValue" @update:model-value="onChange">
      <el-radio-button v-for="opt in options" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </el-radio-button>
    </el-radio-group>
  </div>
</template>

<script setup lang="ts">
import { library } from '@fortawesome/fontawesome-svg-core'
import { faCalendar } from '@fortawesome/free-solid-svg-icons'
import { today, offsetDate } from '@/utils/format'

library.add(faCalendar)

export interface TimeRangeOption {
  label: string
  value: string | number
  hours?: number
  days?: number
  endDays?: number
}

export interface TimeRangeParams {
  hours?: number
  start_date?: string
  end_date?: string
}

const props = defineProps<{
  options: TimeRangeOption[]
  modelValue: string | number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  'params-change': [params: TimeRangeParams]
}>()

function onChange(val: string | number | boolean | undefined) {
  if (val == null) return
  emit('update:modelValue', val as string | number)
  const opt = props.options.find((o) => o.value === val)
  if (!opt) return

  if (opt.hours != null) {
    emit('params-change', { hours: opt.hours })
  } else if (opt.days != null) {
    const t = today()
    const end = opt.endDays != null ? offsetDate(-opt.endDays) : t
    emit('params-change', { start_date: offsetDate(-opt.days), end_date: end })
  }
}
</script>

<style lang="scss" scoped>
.time-range-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 10px 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);

  .filter-label {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    white-space: nowrap;
  }
}
</style>
