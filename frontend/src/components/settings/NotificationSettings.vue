<template>
  <div v-loading="loading" class="tab-content">
    <!-- 通知策略 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <span class="section-title">通知策略</span>
      </template>
      <el-form v-if="strategy" label-width="200px" class="settings-form">
        <el-form-item label="首个成功即停止">
          <el-switch v-model="strategy.stop_on_first_success" @change="saveStrategy" />
          <span class="form-hint">
            {{
              strategy.stop_on_first_success
                ? '任一渠道成功后不再尝试后续渠道'
                : '所有启用渠道全部发送'
            }}
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 渠道列表 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header-row">
          <span class="section-title">通知渠道</span>
          <el-button type="primary" size="small" @click="openAddDialog">
            <font-awesome-icon icon="plus" /> 新增渠道
          </el-button>
        </div>
      </template>

      <el-table v-if="channels.length" :data="sortedChannels" stripe size="small">
        <el-table-column prop="display_name" label="渠道名称" width="140" />
        <el-table-column prop="channel_type" label="类型" width="100" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              :model-value="asChannel(row).enabled"
              size="small"
              @change="(val) => toggleChannel(asChannel(row), !!val)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90" align="center" />
        <el-table-column label="配置摘要" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="config-summary">{{ summarizeConfig(asChannel(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEditDialog(asChannel(row))"
              >编辑</el-button
            >
            <el-button text type="danger" size="small" @click="handleDelete(asChannel(row))"
              >删除</el-button
            >
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无通知渠道" :image-size="60" />
    </el-card>

    <!-- 新增/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingChannel ? '编辑渠道' : '新增渠道'"
      width="520px"
      @close="resetDialog"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="100px"
        class="settings-form"
      >
        <el-form-item label="渠道类型" prop="channel_type">
          <el-select
            v-model="form.channel_type"
            :disabled="!!editingChannel"
            placeholder="选择渠道类型"
            @change="onChannelTypeChange"
          >
            <el-option label="企业微信" value="wechat" />
            <el-option label="邮件通知" value="email" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="form.display_name" placeholder="如：企业微信" />
        </el-form-item>
        <el-form-item label="优先级" prop="priority">
          <el-input-number v-model="form.priority" :min="1" :max="999" />
          <span class="form-hint">越小越优先</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>

        <el-divider />

        <!-- 企业微信配置 -->
        <template v-if="form.channel_type === 'wechat'">
          <el-form-item label="Webhook URL" prop="config.webhook_url">
            <el-input
              v-model="form.config.webhook_url"
              type="textarea"
              :rows="3"
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
            />
          </el-form-item>
        </template>

        <!-- 邮件配置 -->
        <template v-if="form.channel_type === 'email'">
          <el-form-item label="SMTP 服务器" prop="config.smtp_server">
            <el-input v-model="form.config.smtp_server" placeholder="smtp.qq.com" />
          </el-form-item>
          <el-form-item label="SMTP 端口" prop="config.smtp_port">
            <el-input-number v-model="form.config.smtp_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="发件邮箱" prop="config.sender_email">
            <el-input v-model="form.config.sender_email" placeholder="your@email.com" />
          </el-form-item>
          <el-form-item label="发件密码" prop="config.sender_password">
            <el-input
              v-model="form.config.sender_password"
              type="password"
              show-password
              placeholder="授权码或密码"
            />
          </el-form-item>
          <el-form-item label="收件邮箱" prop="config.receiver_email">
            <el-input v-model="form.config.receiver_email" placeholder="receiver@email.com" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { notificationChannelApi, notificationStrategyApi } from '@/api/modules/notification'
import type {
  NotificationChannelModel,
  NotificationStrategyModel,
  NotificationChannelConfig,
} from '@/api/modules/notification'

library.add(faPlus)

const channels = ref<NotificationChannelModel[]>([])
const strategy = ref<NotificationStrategyModel | null>(null)
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingChannel = ref<NotificationChannelModel | null>(null)
const formRef = ref()

const sortedChannels = computed(() => [...channels.value].sort((a, b) => a.priority - b.priority))

const asChannel = (row: unknown) => row as NotificationChannelModel

const defaultConfig = (type: string): NotificationChannelConfig => {
  if (type === 'wechat') return { webhook_url: '' }
  if (type === 'email')
    return {
      smtp_server: '',
      smtp_port: 587,
      sender_email: '',
      sender_password: '',
      receiver_email: '',
    }
  return {}
}

const form = reactive<{
  channel_type: string
  display_name: string
  enabled: boolean
  priority: number
  config: NotificationChannelConfig
}>({
  channel_type: 'wechat',
  display_name: '',
  enabled: true,
  priority: 10,
  config: defaultConfig('wechat'),
})

const formRules = {
  channel_type: [{ required: true, message: '请选择渠道类型', trigger: 'change' }],
  display_name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  priority: [{ required: true, message: '请输入优先级', trigger: 'blur' }],
}

const loadData = async () => {
  loading.value = true
  try {
    const [ch, st] = await Promise.all([
      notificationChannelApi.getChannels(),
      notificationStrategyApi.getStrategy(),
    ])
    channels.value = ch
    strategy.value = st
  } catch {
    /* ignore */
  } finally {
    loading.value = false
  }
}

const saveStrategy = async () => {
  if (!strategy.value) return
  try {
    await notificationStrategyApi.updateStrategy(strategy.value)
    ElMessage.success('策略已更新')
  } catch {
    /* ignore */
  }
}

const toggleChannel = async (row: NotificationChannelModel, val: boolean) => {
  try {
    await notificationChannelApi.updateChannel(row.channel_type, { ...row, enabled: val })
    row.enabled = val
    ElMessage.success(`${row.display_name} 已${val ? '启用' : '禁用'}`)
  } catch {
    /* ignore */
  }
}

const openAddDialog = () => {
  editingChannel.value = null
  form.channel_type = 'wechat'
  form.display_name = ''
  form.enabled = true
  form.priority = 10
  form.config = defaultConfig('wechat')
  dialogVisible.value = true
}

const openEditDialog = (row: NotificationChannelModel) => {
  editingChannel.value = row
  form.channel_type = row.channel_type
  form.display_name = row.display_name
  form.enabled = row.enabled
  form.priority = row.priority
  form.config = { ...row.config }
  dialogVisible.value = true
}

const resetDialog = () => {
  editingChannel.value = null
}

const onChannelTypeChange = (type: string) => {
  form.config = defaultConfig(type)
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload: NotificationChannelModel = {
      channel_type: form.channel_type,
      display_name: form.display_name,
      enabled: form.enabled,
      priority: form.priority,
      config: form.config,
    }
    await notificationChannelApi.updateChannel(form.channel_type, payload)
    ElMessage.success(editingChannel.value ? '渠道已更新' : '渠道已创建')
    dialogVisible.value = false
    await loadData()
  } catch {
    /* ignore */
  } finally {
    saving.value = false
  }
}

const handleDelete = async (row: NotificationChannelModel) => {
  try {
    await ElMessageBox.confirm(`确定要删除渠道「${row.display_name}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await notificationChannelApi.deleteChannel(row.channel_type)
    ElMessage.success(`渠道「${row.display_name}」已删除`)
    await loadData()
  } catch {
    /* user cancelled or error */
  }
}

const summarizeConfig = (row: NotificationChannelModel): string => {
  if (row.channel_type === 'wechat') {
    const url = row.config?.webhook_url ?? ''
    return url ? url.slice(0, 50) + (url.length > 50 ? '...' : '') : '未配置'
  }
  if (row.channel_type === 'email') {
    const to = row.config?.receiver_email ?? ''
    return to ? `发至 ${to}` : '未配置'
  }
  return '—'
}

onMounted(loadData)
</script>

<style lang="scss" scoped>
.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.section-card {
  margin-bottom: 16px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .section-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .card-header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
}

.settings-form {
  .form-hint {
    margin-left: 10px;
    font-size: 13px;
    color: var(--text-secondary);
  }
}

.config-summary {
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
