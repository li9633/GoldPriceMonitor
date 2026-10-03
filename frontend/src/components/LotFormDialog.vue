<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="560px"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
    @open="resetForm"
  >
    <el-alert v-if="isOpening" type="info" :closable="false" class="opening-tip">
      填入你现在<strong>实际持有</strong>的克数与平均成本即可，不必逐笔回忆历史买入。
    </el-alert>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="品种" prop="symbol">
        <el-select
          v-model="form.symbol"
          filterable
          allow-create
          default-first-option
          placeholder="选择或输入品种代码"
          style="width: 100%"
        >
          <el-option v-for="item in symbols" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>

      <el-form-item :label="isOpening ? '持有克数' : '买入克数'" prop="grams">
        <el-input-number
          v-model="form.grams"
          :min="0.001"
          :step="1"
          :precision="3"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item :label="isOpening ? '平均成本价' : '买入单价'" prop="price_per_gram">
        <el-input-number
          v-model="form.price_per_gram"
          :min="0.01"
          :step="1"
          :precision="2"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="按金额换算">
        <div class="amount-row">
          <el-input-number v-model="amount" :min="0" :step="100" :precision="2" />
          <el-button text type="primary" :disabled="!canDerive" @click="derivePrice">
            换算单价
          </el-button>
          <span class="amount-hint">{{ derivedHint }}</span>
        </div>
        <div v-if="isOpening" class="field-hint">
          记不清均价、但知道一共投入了多少钱时，在这里填总金额再点「换算单价」
        </div>
      </el-form-item>

      <el-form-item :label="isOpening ? '大致日期' : '买入日期'" prop="trade_date">
        <el-date-picker
          v-model="form.trade_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择日期"
          style="width: 100%"
        />
        <div v-if="isOpening" class="field-hint">
          只用于统计与回访判断，记不清具体哪天可以填个大概
        </div>
      </el-form-item>

      <template v-if="!isOpening">
        <el-form-item label="手续费">
          <el-input-number
            v-model="form.fee"
            :min="0"
            :step="1"
            :precision="2"
            style="width: 100%"
          />
          <div class="field-hint">只做记录，不计入成本价</div>
        </el-form-item>

        <el-form-item label="渠道">
          <el-input v-model="form.channel" placeholder="金店 / 银行积存金 / ETF …" />
        </el-form-item>

        <el-form-item label="所属计划">
          <el-select v-model="form.plan_id" clearable placeholder="不关联计划" style="width: 100%">
            <el-option
              v-for="item in plans"
              :key="item.id"
              :label="planLabel(item)"
              :value="item.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">
        {{ isOpening ? '保存持仓' : '保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { portfolioApi } from '@/api/modules/portfolio'
import type { PurchaseLot, PurchaseLotPayload, PurchasePlan } from '@/api/modules/portfolio'
import { formatPrice, today } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    lot?: PurchaseLot | null
    plans?: PurchasePlan[]
    symbols?: string[]
    defaultSymbol?: string
    /** `opening` = 录入「现在已经持有的仓位」，只问克数与均价 */
    mode?: 'lot' | 'opening'
  }>(),
  {
    lot: null,
    plans: () => [],
    symbols: () => [],
    defaultSymbol: '',
    mode: 'lot'
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)
/** 辅助输入：知道「一共花了多少钱」时反推单价 */
const amount = ref<number>()

const isEdit = computed(() => props.lot != null)
const isOpening = computed(() => props.mode === 'opening')

const dialogTitle = computed(() => {
  if (isOpening.value) return '录入当前持仓'
  return isEdit.value ? '编辑买入记录' : '新增买入记录'
})

const form = ref<PurchaseLotPayload>({
  symbol: '',
  trade_date: today(),
  grams: 1,
  price_per_gram: 0,
  fee: 0,
  channel: '',
  note: '',
  plan_id: null
})

const rules: FormRules = {
  symbol: [{ required: true, message: '请选择或输入品种', trigger: 'change' }],
  trade_date: [{ required: true, message: '请选择买入日期', trigger: 'change' }],
  grams: [{ required: true, message: '请输入买入克数', trigger: 'blur' }],
  price_per_gram: [{ required: true, message: '请输入买入单价', trigger: 'blur' }]
}

const canDerive = computed(() => (amount.value ?? 0) > 0 && (form.value.grams ?? 0) > 0)

const derivedHint = computed(() => {
  if (!canDerive.value) return '填总花费 + 克数可反推单价'
  return `≈ ${formatPrice((amount.value as number) / (form.value.grams as number))} /克`
})

function derivePrice() {
  if (!canDerive.value) return
  form.value.price_per_gram = Number(
    ((amount.value as number) / (form.value.grams as number)).toFixed(2)
  )
}

function planLabel(plan: PurchasePlan) {
  const mode = plan.tranches > 1 ? `分 ${plan.tranches} 批` : '一次性'
  return `#${plan.id} ${plan.symbol} ${plan.target_grams}g（${mode}）`
}

function resetForm() {
  const source = props.lot
  amount.value = undefined
  if (source) {
    form.value = {
      symbol: source.symbol,
      trade_date: source.trade_date,
      grams: source.grams,
      price_per_gram: source.price_per_gram,
      fee: source.fee,
      channel: source.channel,
      note: source.note,
      plan_id: source.plan_id,
      is_opening: source.is_opening
    }
  } else {
    form.value = {
      symbol: props.defaultSymbol,
      trade_date: today(),
      grams: 1,
      price_per_gram: 0,
      fee: 0,
      channel: '',
      note: '',
      plan_id: null,
      is_opening: isOpening.value
    }
  }
  formRef.value?.clearValidate()
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    const payload: PurchaseLotPayload = { ...form.value }
    if (isEdit.value && props.lot) {
      await portfolioApi.updateLot(props.lot.id, payload)
      ElMessage.success('已更新')
    } else {
      await portfolioApi.createLot(payload)
      ElMessage.success(isOpening.value ? '已录入当前持仓' : '已记录')
    }
    emit('saved')
    emit('update:modelValue', false)
  } catch {
    // 错误提示已由 request 拦截器统一处理
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.opening-tip {
  margin-bottom: 16px;
}

.amount-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;

  .amount-hint {
    font-size: 12px;
    color: var(--text-muted);
  }
}

.field-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
