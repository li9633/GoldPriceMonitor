<template>
  <div class="providers">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="server" /> 模型池管理</h1>
      <el-button type="primary" @click="openCreateDialog">
        <font-awesome-icon icon="plus" /> 新增供应商
      </el-button>
    </div>

    <el-card v-for="provider in providers" :key="provider.id" class="provider-card">
      <template #header>
        <div class="provider-header">
          <span class="provider-name">{{ provider.name }}</span>
          <div class="provider-actions">
            <el-button text type="primary" @click="openEditDialog(provider)">编辑</el-button>
            <el-button text type="danger" @click="handleDelete(provider)">删除</el-button>
          </div>
        </div>
      </template>
      <div class="provider-info">
        <el-tag v-for="model in provider.models" :key="model" size="small" class="model-tag">
          {{ model }}
        </el-tag>
        <span v-if="!provider.models.length" class="no-model">暂无模型</span>
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑供应商' : '新增供应商'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="form.api_url" />
        </el-form-item>
        <el-form-item label="API 密钥">
          <el-input v-model="form.api_key" />
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
import type { ModelProvider, ProviderCreate, ProviderUpdate } from '@/api/modules/aiProvider'

library.add(faServer, faPlus)

const providers = ref<ModelProvider[]>([])
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

const loadProviders = async () => {
  providers.value = await providerApi.list()
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
  loadProviders()
}

const handleDelete = async (provider: ModelProvider) => {
  try {
    await ElMessageBox.confirm(`确定删除供应商「${provider.name}」？`, '确认删除', {
      type: 'warning',
    })
    await providerApi.remove(provider.name)
    ElMessage.success('删除成功')
    loadProviders()
  } catch {
    // 取消操作
  }
}

onMounted(loadProviders)
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

.provider-card {
  margin-bottom: 16px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .provider-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .provider-name {
    font-weight: bold;
    font-size: 15px;
    color: var(--text-primary);
  }

  .provider-actions {
    display: flex;
    gap: 4px;
  }
}

.provider-info {
  .model-tag {
    margin-right: 8px;
    margin-bottom: 4px;
  }

  .no-model {
    color: var(--text-muted);
    font-size: 13px;
  }
}
</style>
