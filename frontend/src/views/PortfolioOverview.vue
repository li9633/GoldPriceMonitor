<template>
  <div class="portfolio">
    <div class="page-header">
      <div class="header-actions">
        <el-button text :loading="loading" @click="refreshAll">
          <font-awesome-icon icon="rotate" /> 刷新
        </el-button>
        <el-button type="primary" @click="openLotDialog()">
          <font-awesome-icon icon="plus" /> 记一笔买入
        </el-button>
        <el-button @click="openPlanDialog()">
          <font-awesome-icon icon="layer-group" /> 新建计划
        </el-button>
      </div>
      <div class="header-left">
        <h1 class="page-title"><font-awesome-icon icon="coins" /> 我的持仓</h1>
        <p class="page-subtitle">记录买入、跟踪成本与浮盈亏，并管理分批买入计划</p>
      </div>
    </div>

    <PositionSummary :summary="summary" />

    <el-card class="section-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">购买计划</span>
          <span class="card-hint">「分几批」用来回答一次性还是分批买入</span>
        </div>
      </template>
      <el-table :data="summary?.plans ?? []" size="small" empty-text="还没有购买计划">
        <el-table-column label="计划" min-width="120">
          <template #default="{ row }">
            <span class="mono">#{{ row.plan_id }}</span>
            <span class="muted"> {{ row.symbol }}</span>
          </template>
        </el-table-column>
        <el-table-column label="方式" width="90">
          <template #default="{ row }">
            {{ row.tranches > 1 ? `分 ${row.tranches} 批` : '一次性' }}
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(row.progress_pct, 100)"
              :stroke-width="12"
              :status="row.progress_pct >= 100 ? 'success' : undefined"
            />
            <div class="progress-text">
              {{ row.filled_grams }} / {{ row.target_grams }} g
              <span v-if="row.progress_pct > 100" class="over"
                >（超买 {{ row.progress_pct }}%）</span
              >
            </div>
          </template>
        </el-table-column>
        <el-table-column label="已投入" width="120" align="right">
          <template #default="{ row }">{{ formatPrice(row.invested_amount) }}</template>
        </el-table-column>
        <el-table-column label="成本价" width="110" align="right">
          <template #default="{ row }">
            {{ row.avg_cost > 0 ? formatPrice(row.avg_cost) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="right">
          <template #default="{ row }">
            <el-button
              text
              type="primary"
              size="small"
              @click="togglePlanStatus(row as PlanProgress)"
            >
              {{ row.status === 'active' ? '暂停' : '启用' }}
            </el-button>
            <el-button text type="danger" size="small" @click="removePlan(row as PlanProgress)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">买入记录</span>
          <span class="card-hint">共 {{ lots.length }} 笔</span>
        </div>
      </template>
      <el-table :data="lots" size="small" empty-text="还没有买入记录，点右上角「记一笔买入」">
        <el-table-column prop="trade_date" label="日期" width="110" sortable />
        <el-table-column prop="symbol" label="品种" width="120" />
        <el-table-column label="克数" width="100" align="right">
          <template #default="{ row }">{{ row.grams }}</template>
        </el-table-column>
        <el-table-column label="单价" width="110" align="right">
          <template #default="{ row }">{{ formatPrice(row.price_per_gram) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="right">
          <template #default="{ row }">{{ formatPrice(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="手续费" width="100" align="right">
          <template #default="{ row }">
            {{ row.fee > 0 ? formatPrice(row.fee) : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="channel" label="渠道" min-width="110">
          <template #default="{ row }">{{ row.channel || '—' }}</template>
        </el-table-column>
        <el-table-column label="计划" width="90">
          <template #default="{ row }">
            <span v-if="row.plan_id" class="mono">#{{ row.plan_id }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="120" align="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openLotDialog(row as PurchaseLot)">
              编辑
            </el-button>
            <el-button text type="danger" size="small" @click="removeLot(row as PurchaseLot)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <LotFormDialog
      v-model="lotDialogVisible"
      :lot="editingLot"
      :plans="plans"
      :symbols="symbolCodes"
      :default-symbol="defaultSymbol"
      @saved="refreshAll"
    />

    <el-dialog v-model="planDialogVisible" title="新建购买计划" width="520px">
      <el-form ref="planFormRef" :model="planForm" :rules="planRules" label-width="110px">
        <el-form-item label="品种" prop="symbol">
          <el-select
            v-model="planForm.symbol"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
          >
            <el-option v-for="item in symbolCodes" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划总克数" prop="target_grams">
          <el-input-number
            v-model="planForm.target_grams"
            :min="1"
            :step="10"
            :precision="2"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="买入方式">
          <el-radio-group v-model="planMode">
            <el-radio-button value="once">一次性</el-radio-button>
            <el-radio-button value="split">分批</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="planMode === 'split'" label="分几批">
          <el-input-number v-model="planForm.tranches" :min="2" :max="60" :step="1" />
          <span class="field-hint">每批约 {{ trancheGrams }} g</span>
        </el-form-item>
        <el-form-item v-if="planMode === 'split'" label="触发方式">
          <el-select v-model="triggerType" style="width: 100%">
            <el-option label="按时间间隔" value="interval" />
            <el-option label="按跌幅补仓" value="drop_pct" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="planMode === 'split' && triggerType === 'interval'" label="间隔天数">
          <el-input-number v-model="triggerDays" :min="1" :max="365" :step="1" />
        </el-form-item>
        <el-form-item v-if="planMode === 'split' && triggerType === 'drop_pct'" label="跌幅阈值">
          <el-input-number v-model="triggerPct" :min="0.1" :max="50" :step="0.5" :precision="1" />
          <span class="field-hint">%</span>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker
            v-model="planForm.start_date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="planSaving" @click="submitPlan">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faCoins, faLayerGroup, faPlus, faRotate } from '@fortawesome/free-solid-svg-icons'
import { portfolioApi } from '@/api/modules/portfolio'
import type {
  PlanProgress,
  PlanStatus,
  PortfolioSummary,
  PurchaseLot,
  PurchasePlan,
  PurchasePlanPayload
} from '@/api/modules/portfolio'
import { settingsApi } from '@/api/modules/settings'
import { formatPrice, today } from '@/utils/format'
import PositionSummary from '@/components/PositionSummary.vue'
import LotFormDialog from '@/components/LotFormDialog.vue'

library.add(faCoins, faLayerGroup, faPlus, faRotate)

const loading = ref(false)
const summary = ref<PortfolioSummary | null>(null)
const lots = ref<PurchaseLot[]>([])
const plans = ref<PurchasePlan[]>([])
const symbolCodes = ref<string[]>([])
const defaultSymbol = ref('')

const lotDialogVisible = ref(false)
const editingLot = ref<PurchaseLot | null>(null)

const planDialogVisible = ref(false)
const planSaving = ref(false)
const planFormRef = ref<FormInstance>()
const planMode = ref<'once' | 'split'>('split')
const triggerType = ref<'interval' | 'drop_pct'>('interval')
const triggerDays = ref(7)
const triggerPct = ref(1)

const planForm = ref<PurchasePlanPayload>({
  symbol: '',
  target_grams: 100,
  tranches: 4,
  start_date: today()
})

const planRules: FormRules = {
  symbol: [{ required: true, message: '请选择或输入品种', trigger: 'change' }],
  target_grams: [{ required: true, message: '请输入计划总克数', trigger: 'blur' }]
}

const trancheGrams = computed(() => {
  const total = planForm.value.target_grams ?? 0
  const tranches = Math.max(planForm.value.tranches ?? 1, 1)
  return (total / tranches).toFixed(2)
})

async function loadLots() {
  lots.value = await portfolioApi.listLots()
}

async function loadPlans() {
  plans.value = await portfolioApi.listPlans()
}

async function loadSummary() {
  summary.value = await portfolioApi.getSummary()
}

async function loadSymbols() {
  try {
    const mappings = await settingsApi.getSymbols()
    symbolCodes.value = mappings.map((item) => item.symbol)
    defaultSymbol.value = symbolCodes.value[0] ?? ''
  } catch {
    // 拿不到品种配置也不影响记账
    symbolCodes.value = []
  }
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([loadLots(), loadPlans(), loadSummary()])
  } catch {
    // 错误提示已由 request 拦截器统一处理
  } finally {
    loading.value = false
  }
}

function openLotDialog(row?: PurchaseLot) {
  editingLot.value = row ?? null
  lotDialogVisible.value = true
}

async function removeLot(row: PurchaseLot) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${row.trade_date} 的 ${row.grams}g 买入记录？`,
      '删除买入记录',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await portfolioApi.deleteLot(row.id)
    ElMessage.success('已删除')
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  }
}

function openPlanDialog() {
  planMode.value = 'split'
  triggerType.value = 'interval'
  triggerDays.value = 7
  triggerPct.value = 1
  planForm.value = {
    symbol: defaultSymbol.value,
    target_grams: 100,
    tranches: 4,
    start_date: today()
  }
  planDialogVisible.value = true
}

async function submitPlan() {
  const valid = await planFormRef.value?.validate().catch(() => false)
  if (!valid) return

  const payload: PurchasePlanPayload = { ...planForm.value }
  if (planMode.value === 'once') {
    payload.tranches = 1
    payload.trigger_policy = {}
  } else {
    payload.tranches = planForm.value.tranches ?? 4
    payload.trigger_policy =
      triggerType.value === 'interval'
        ? { type: 'interval', days: triggerDays.value }
        : { type: 'drop_pct', pct: triggerPct.value }
  }

  planSaving.value = true
  try {
    await portfolioApi.createPlan(payload)
    ElMessage.success('计划已创建')
    planDialogVisible.value = false
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    planSaving.value = false
  }
}

async function togglePlanStatus(row: PlanProgress) {
  const next: PlanStatus = row.status === 'active' ? 'paused' : 'active'
  try {
    await portfolioApi.updatePlan(row.plan_id, { status: next })
    ElMessage.success(next === 'active' ? '已启用' : '已暂停')
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  }
}

async function removePlan(row: PlanProgress) {
  try {
    await ElMessageBox.confirm(
      '删除计划不会删除已记录的买入，只会解除关联。确认删除？',
      '删除购买计划',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await portfolioApi.deletePlan(row.plan_id)
    ElMessage.success('已删除')
    await refreshAll()
  } catch {
    /* 拦截器已提示 */
  }
}

function statusLabel(status: PlanStatus) {
  return { active: '进行中', paused: '已暂停', done: '已完成', cancelled: '已取消' }[status]
}

function statusTagType(status: PlanStatus): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  if (status === 'cancelled') return 'danger'
  return 'info'
}

onMounted(async () => {
  await loadSymbols()
  await refreshAll()
})
</script>

<style lang="scss" scoped>
.portfolio {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 28px;

  .header-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .header-left {
    text-align: center;
  }

  .page-title {
    font-size: 24px;
    color: var(--text-primary);
    margin: 0 0 6px 0;
  }

  .page-subtitle {
    font-size: 14px;
    color: var(--text-secondary);
    margin: 0;
  }
}

.section-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  margin-bottom: 20px;

  .card-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }

  .card-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .card-hint {
    font-size: 12px;
    color: var(--text-muted);
  }
}

.progress-text {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;

  .over {
    color: var(--price-up);
  }
}

.field-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: 8px;
}

.mono {
  font-family: monospace;
  color: var(--text-primary);
}

.muted {
  color: var(--text-muted);
}
</style>
