<template>
  <div v-loading="loading" class="tab-content">
    <div class="tab-toolbar">
      <el-button type="primary" @click="openAdd">
        <font-awesome-icon icon="plus" /> 新增品种
      </el-button>
    </div>
    <el-table :data="symbols" stripe border class="symbol-table">
      <el-table-column prop="symbol" label="品种代码" width="180" />
      <el-table-column prop="display_name" label="显示名称" width="200" />
      <el-table-column prop="sort_order" label="排序权重" width="120" align="center" />
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button text type="primary" size="small" @click="openEdit(row as SymbolMapping)">
            <font-awesome-icon icon="pen" /> 编辑
          </el-button>
          <el-button text type="danger" size="small" @click="handleDelete(row.symbol)">
            <font-awesome-icon icon="trash" /> 删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="showDialog"
      :title="isEditing ? '编辑品种映射' : '新增品种映射'"
      width="480px"
    >
      <el-form label-width="120px">
        <el-form-item label="品种代码">
          <el-input v-model="form.symbol" :disabled="isEditing" placeholder="如 gds_AUTD" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" placeholder="如 黄金延期" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="form.sort_order" :min="0" :max="999" />
          <span class="unit">越小越靠前</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faPlus, faPen, faTrash } from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import type { SymbolMapping } from '@/api/modules/settings'

library.add(faPlus, faPen, faTrash)

const symbols = ref<SymbolMapping[]>([])
const loading = ref(false)
const showDialog = ref(false)
const isEditing = ref(false)
const form = ref<SymbolMapping>({ symbol: '', display_name: '', sort_order: 0 })
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    symbols.value = await settingsApi.getSymbols()
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
}

function openAdd() {
  isEditing.value = false
  form.value = { symbol: '', display_name: '', sort_order: 0 }
  showDialog.value = true
}

function openEdit(row: SymbolMapping) {
  isEditing.value = true
  form.value = { ...row }
  showDialog.value = true
}

async function handleSave() {
  saving.value = true
  try {
    await settingsApi.updateSymbol(form.value.symbol, form.value)
    ElMessage.success(isEditing.value ? '品种配置已更新' : '品种配置已添加')
    showDialog.value = false
    await load()
  } catch {
    /* ignore */
  } finally {
    saving.value = false
  }
}

async function handleDelete(symbol: string) {
  try {
    await ElMessageBox.confirm(`确定要删除品种 [${symbol}] 吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await settingsApi.deleteSymbol(symbol)
    ElMessage.success(`品种 [${symbol}] 已删除`)
    await load()
  } catch {
    /* ignore */
  }
}

onMounted(load)
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.tab-toolbar {
  margin-bottom: 16px;
}

.symbol-table {
  width: 100%;
}

.unit {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
