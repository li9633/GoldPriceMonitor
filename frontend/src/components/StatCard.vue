<template>
  <el-card class="stat-card" shadow="hover">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value" :class="{ 'price-color': highlight }">{{ value }}</div>
    <div v-if="sub" class="stat-sub" :class="subClass">{{ sub }}</div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  label: string
  value: string
  sub?: string
  subClass?: string
  highlight?: boolean
}>()
</script>

<style lang="scss" scoped>
.stat-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  transition:
    transform 0.2s,
    background 0.3s;

  &:hover {
    transform: translateY(-2px);
  }

  .stat-label {
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 8px;
  }

  .stat-value {
    font-size: 26px;
    font-weight: bold;
    color: var(--text-primary);

    &.price-color {
      color: var(--price-color);
    }
  }

  .stat-sub {
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
</style>
