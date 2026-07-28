<template>
  <div class="model-item">
    <div class="model-info">
      <span class="model-name">{{ model.model_name }}</span>
      <span class="model-order">#{{ model.sort_order }}</span>
    </div>
    <div class="model-actions">
      <el-button
        text
        size="small"
        :disabled="isFirst"
        title="上移"
        @click="$emit('move-up', model.id)"
      >
        <font-awesome-icon icon="arrow-up" />
      </el-button>
      <el-button
        text
        size="small"
        :disabled="isLast"
        title="下移"
        @click="$emit('move-down', model.id)"
      >
        <font-awesome-icon icon="arrow-down" />
      </el-button>
      <el-button text size="small" type="primary" title="编辑" @click="$emit('edit', model)">
        <font-awesome-icon icon="pen" />
      </el-button>
      <el-button text size="small" type="danger" title="删除" @click="$emit('delete', model)">
        <font-awesome-icon icon="trash" />
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { library } from '@fortawesome/fontawesome-svg-core'
import { faArrowUp, faArrowDown, faPen, faTrash } from '@fortawesome/free-solid-svg-icons'
import type { ProviderModel } from '@/api/modules/aiProvider'

library.add(faArrowUp, faArrowDown, faPen, faTrash)

defineProps<{
  model: ProviderModel
  isFirst: boolean
  isLast: boolean
}>()

defineEmits<{
  'move-up': [modelId: number]
  'move-down': [modelId: number]
  edit: [model: ProviderModel]
  delete: [model: ProviderModel]
}>()
</script>

<style lang="scss" scoped>
.model-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  transition: background 0.2s;

  &:hover {
    background: var(--color-primary-bg);
  }

  + .model-item {
    margin-top: 6px;
  }

  .model-info {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .model-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .model-order {
    font-size: 12px;
    color: var(--text-muted);
    background: var(--border-color);
    padding: 1px 6px;
    border-radius: 4px;
  }

  .model-actions {
    display: flex;
    align-items: center;
    gap: 2px;
  }
}
</style>
