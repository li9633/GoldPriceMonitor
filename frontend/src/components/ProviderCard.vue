<template>
  <el-card class="provider-card">
    <template #header>
      <div class="provider-header">
        <div class="provider-title" @click="expanded = !expanded">
          <font-awesome-icon
            :icon="expanded ? 'chevron-down' : 'chevron-right'"
            class="expand-icon"
          />
          <span class="provider-name">{{ provider.name }}</span>
          <el-tag
            size="small"
            :type="provider.api_key === '未设置' ? 'danger' : 'success'"
            effect="plain"
          >
            {{ provider.api_key === '未设置' ? '未配置 Key' : '已配置' }}
          </el-tag>
          <el-tag size="small" type="warning" effect="plain">{{ models.length }} 个模型</el-tag>
        </div>
        <div class="provider-actions">
          <el-button text size="small" type="primary" @click="$emit('edit', provider)">
            <font-awesome-icon icon="pen" /> 编辑
          </el-button>
          <el-button text size="small" type="danger" @click="$emit('delete', provider)">
            <font-awesome-icon icon="trash" /> 删除
          </el-button>
        </div>
      </div>
    </template>

    <el-collapse-transition>
      <div v-show="expanded" class="provider-body">
        <div class="model-section">
          <div class="model-section-header">
            <span class="section-title">模型列表</span>
            <el-button size="small" text type="primary" @click="openAddModel">
              <font-awesome-icon icon="plus" /> 添加模型
            </el-button>
          </div>

          <div v-if="models.length === 0" class="model-empty">
            <font-awesome-icon icon="cube" class="empty-icon" />
            <span>暂无模型，点击上方按钮添加</span>
          </div>

          <ModelItem
            v-for="(model, index) in sortedModels"
            :key="model.id"
            :model="model"
            :is-first="index === 0"
            :is-last="index === sortedModels.length - 1"
            @move-up="(id: number) => $emit('move-model', id, 'up')"
            @move-down="(id: number) => $emit('move-model', id, 'down')"
            @edit="openEditModel"
            @delete="(m: ProviderModel) => $emit('delete-model', m)"
          />
        </div>
      </div>
    </el-collapse-transition>

    <el-dialog
      v-model="modelDialogVisible"
      :title="editingModel ? '编辑模型' : '添加模型'"
      width="420px"
    >
      <el-form :model="modelForm" label-width="100px">
        <el-form-item label="模型名称">
          <el-input v-model="modelForm.model_name" placeholder="如：glm-4-plus" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="modelForm.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleModelSubmit">确定</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faChevronDown,
  faChevronRight,
  faPen,
  faTrash,
  faPlus,
  faCube,
} from '@fortawesome/free-solid-svg-icons'
import type {
  ModelProvider,
  ProviderModel,
  ProviderModelCreate,
  ProviderModelUpdate,
} from '@/api/modules/aiProvider'
import ModelItem from '@/components/ModelItem.vue'

library.add(faChevronDown, faChevronRight, faPen, faTrash, faPlus, faCube)

const props = defineProps<{
  provider: ModelProvider
  models: ProviderModel[]
}>()

const emit = defineEmits<{
  edit: [provider: ModelProvider]
  delete: [provider: ModelProvider]
  'add-model': [providerName: string, data: ProviderModelCreate]
  'edit-model': [providerName: string, modelId: number, data: ProviderModelUpdate]
  'delete-model': [model: ProviderModel]
  'move-model': [modelId: number, direction: 'up' | 'down']
}>()

const expanded = ref(true)
const modelDialogVisible = ref(false)
const editingModel = ref<ProviderModel | null>(null)

const modelForm = ref<ProviderModelCreate>({
  provider_name: props.provider.name,
  model_name: '',
  sort_order: 0,
})

const sortedModels = computed(() => {
  return [...props.models].sort((a, b) => a.sort_order - b.sort_order)
})

const openAddModel = () => {
  editingModel.value = null
  modelForm.value = {
    provider_name: props.provider.name,
    model_name: '',
    sort_order:
      props.models.length > 0 ? Math.max(...props.models.map((m) => m.sort_order)) + 1 : 0,
  }
  modelDialogVisible.value = true
}

const openEditModel = (model: ProviderModel) => {
  editingModel.value = model
  modelForm.value = {
    provider_name: model.provider_name,
    model_name: model.model_name,
    sort_order: model.sort_order,
  }
  modelDialogVisible.value = true
}

const handleModelSubmit = () => {
  if (editingModel.value) {
    emit('edit-model', props.provider.name, editingModel.value.id, {
      model_name: modelForm.value.model_name,
      sort_order: modelForm.value.sort_order,
    })
  } else {
    emit('add-model', props.provider.name, { ...modelForm.value })
  }
  modelDialogVisible.value = false
}
</script>

<style lang="scss" scoped>
.provider-card {
  margin-bottom: 16px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .provider-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .provider-title {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    user-select: none;

    .expand-icon {
      font-size: 13px;
      color: var(--text-muted);
      transition: transform 0.2s;
    }

    .provider-name {
      font-weight: bold;
      font-size: 15px;
      color: var(--text-primary);
    }
  }

  .provider-actions {
    display: flex;
    gap: 4px;
  }

  .provider-body {
    padding-top: 4px;
  }

  .model-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;

    .section-title {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
    }
  }

  .model-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 24px;
    color: var(--text-muted);
    font-size: 13px;

    .empty-icon {
      font-size: 28px;
      opacity: 0.4;
    }
  }
}
</style>
