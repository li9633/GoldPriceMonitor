<template>
  <span class="trend-badge" :class="direction">
    <font-awesome-icon :icon="icon" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faArrowUp, faArrowDown, faMinus } from '@fortawesome/free-solid-svg-icons'

library.add(faArrowUp, faArrowDown, faMinus)

const props = defineProps<{
  direction: 'up' | 'down' | 'stable'
}>()

const icon = computed(() => {
  return { up: 'arrow-up', down: 'arrow-down', stable: 'minus' }[props.direction]
})

const label = computed(() => {
  return { up: '上涨', down: '下跌', stable: '平稳' }[props.direction]
})
</script>

<style lang="scss" scoped>
.trend-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;

  &.up {
    color: var(--price-up);
    background: rgba(212, 53, 28, 0.08);
  }
  &.down {
    color: var(--price-down);
    background: rgba(28, 168, 94, 0.08);
  }
  &.stable {
    color: var(--text-muted);
    background: rgba(160, 160, 160, 0.08);
  }
}
</style>
