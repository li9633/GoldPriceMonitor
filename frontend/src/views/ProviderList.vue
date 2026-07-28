<template>
  <div class="providers">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="server" /> 模型池管理</h1>
      <el-button type="primary" @click="openCreateDialog">
        <font-awesome-icon icon="plus" /> 新增供应商
      </el-button>
    </div>

    <ProviderCard
      v-for="provider in providers"
      :key="provider.id"
      :provider="provider"
      :models="getProviderModels(provider.name)"
      @edit="openEditDialog"
      @delete="handleDelete"
      @add-model="handleAddModel"
      @edit-model="handleEditModel"
      @delete-model="handleDeleteModel"
      @move-model="handleMoveModel"
    />

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑供应商' : '新增供应商'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="form.api_url" />
        </el-form-item>
        <el-form-item label="环境变量名">
          <el-input v-model="form.api_key" placeholder="如：GLM_API_KEY" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout" :min="1" :max="120" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faServer, faPlus } from '@fortawesome/free-solid-svg-icons'
import { providerApi } from '@/api/modules/aiProvider'
import type {
  ModelProvider,
  ProviderModel,
  ProviderCreate,
  ProviderUpdate,
  ProviderModelCreate,
  ProviderModelUpdate,
} from '@/api/modules/aiProvider'
import ProviderCard from '@/components/ProviderCard.vue'

library.add(faServer, faPlus)

const providers = ref<ModelProvider[]>([])
const modelsMap = ref<Record<string, ProviderModel[]>>({})
const dialogVisible = ref(false)
const isEdit = ref(false)
const editingName = ref('')

const form = ref<ProviderCreate>({
  name: '',
  api_url: '',
  api_key: '',
  timeout: 30,
  sort_order: 0,
})

const getProviderModels = (name: string): ProviderModel[] => {
  return modelsMap.value[name] ?? []
}

const loadAll = async () => {
  providers.value = await providerApi.list()
  const map: Record<string, ProviderModel[]> = {}
  await Promise.all(
    providers.value.map(async (p) => {
      map[p.name] = await providerApi.listModels(p.name)
    }),
  )
  modelsMap.value = map
}

const openCreateDialog = () => {
  isEdit.value = false
  form.value = { name: '', api_url: '', api_key: '', timeout: 30, sort_order: 0 }
  dialogVisible.value = true
}

const openEditDialog = (provider: ModelProvider) => {
  isEdit.value = true
  editingName.value = provider.name
  form.value = {
    name: provider.name,
    api_url: provider.api_url,
    api_key: provider.api_key,
    timeout: provider.timeout,
    sort_order: provider.sort_order,
  }
  dialogVisible.value = true
}

const handleSubmit = async () => {
  if (isEdit.value) {
    const updateData: ProviderUpdate = {
      api_url: form.value.api_url,
      api_key: form.value.api_key,
      timeout: form.value.timeout,
      sort_order: form.value.sort_order,
    }
    await providerApi.update(editingName.value, updateData)
  } else {
    await providerApi.create(form.value)
  }
  dialogVisible.value = false
  loadAll()
}

const handleDelete = async (provider: ModelProvider) => {
  try {
    await ElMessageBox.confirm(`确定删除供应商「${provider.name}」？`, '确认删除', {
      type: 'warning',
    })
    await providerApi.remove(provider.name)
    ElMessage.success('删除成功')
    loadAll()
  } catch {
    // 取消操作
  }
}

const handleAddModel = async (providerName: string, data: ProviderModelCreate) => {
  await providerApi.createModel(providerName, data)
  ElMessage.success('模型添加成功')
  modelsMap.value[providerName] = await providerApi.listModels(providerName)
}

const handleEditModel = async (
  providerName: string,
  modelId: number,
  data: ProviderModelUpdate,
) => {
  await providerApi.updateModel(providerName, modelId, data)
  ElMessage.success('模型更新成功')
  modelsMap.value[providerName] = await providerApi.listModels(providerName)
}

const handleDeleteModel = async (model: ProviderModel) => {
  try {
    await ElMessageBox.confirm(`确定删除模型「${model.model_name}」？`, '确认删除', {
      type: 'warning',
    })
    await providerApi.removeModel(model.provider_name, model.id)
    ElMessage.success('删除成功')
    modelsMap.value[model.provider_name] = await providerApi.listModels(model.provider_name)
  } catch {
    // 取消操作
  }
}

const handleMoveModel = async (modelId: number, direction: 'up' | 'down') => {
  const model = findModelById(modelId)
  if (!model) return

  const models = modelsMap.value[model.provider_name] ?? []
  const sorted = [...models].sort((a, b) => a.sort_order - b.sort_order)
  const idx = sorted.findIndex((m) => m.id === modelId)
  if (idx === -1) return

  const targetIdx = direction === 'up' ? idx - 1 : idx + 1
  if (targetIdx < 0 || targetIdx >= sorted.length) return

  const target = sorted[targetIdx]
  if (!target) return

  await providerApi.updateModel(model.provider_name, model.id, { sort_order: target.sort_order })
  await providerApi.updateModel(model.provider_name, target.id, { sort_order: model.sort_order })

  modelsMap.value[model.provider_name] = await providerApi.listModels(model.provider_name)
}

const findModelById = (id: number): ProviderModel | null => {
  for (const models of Object.values(modelsMap.value)) {
    const found = models.find((m) => m.id === id)
    if (found) return found
  }
  return null
}

onMounted(loadAll)
</script>

<style lang="scss" scoped>
.providers {
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }
}
</style>
