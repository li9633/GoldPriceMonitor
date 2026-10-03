<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑卖出记录' : '记一笔卖出'"
    width="560px"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
    @open="resetForm"
  >
    <el-alert v-if="availableGrams !== null" type="info" :closable="false" class="sale-tip">
      当前持有 <strong>{{ availableGrams }}g</strong>，均价 ¥{{
        formatPrice(availableAvgCost ?? 0)
      }}/克。卖出按<strong>移动平均</strong>结转成本，剩余持仓的成本价不变。
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

      <el-form-item label="卖出克数" prop="grams">
        <el-input-number
          v-model="form.grams"
          :min="0.001"
          :step="1"
          :precision="3"
          style="width: 100%"
        />
        <div v-if="availableGrams !== null" class="field-hint">
          最多可卖 {{ availableGrams }}g
          <el-button text type="primary" size="small" @click="fillAll">全部卖出</el-button>
        </div>
      </el-form-item>

      <el-form-item label="卖出单价" prop="price_per_gram">
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
      </el-form-item>

      <el-form-item label="卖出日期" prop="sale_date">
        <el-date-picker
          v-model="form.sale_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择日期"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="手续费">
        <el-input-number v-model="form.fee" :min="0" :step="1" :precision="2" style="width: 100%" />
        <div class="field-hint">只做记录，不冲减已实现盈亏</div>
      </el-form-item>

      <el-form-item label="渠道">
        <el-input v-model="form.channel" placeholder="金店 / 银行积存金 / ETF …" />
      </el-form-item>

      <el-form-item label="备注">
        <el-input v-model="form.note" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { portfolioApi } from '@/api/modules/portfolio'
import type { SaleRecord, SaleRecordPayload } from '@/api/modules/portfolio'
import { formatPrice, today } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    sale?: SaleRecord | null
    symbols?: string[]
    defaultSymbol?: string
    /** 建议里算出的建议卖出克数 —— 从建议卡直接带过来 */
    defaultGrams?: number | null
    defaultPrice?: number | null
    /** 当前可卖克数与均价，用于提示与「全部卖出」 */
    availableGrams?: number | null
    availableAvgCost?: number | null
  }>(),
  {
    sale: null,
    symbols: () => [],
    defaultSymbol: '',
    defaultGrams: null,
    defaultPrice: null,
    availableGrams: null,
    availableAvgCost: null
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)
/** 辅助输入：知道「一共卖了多少钱」时反推单价 */
const amount = ref<number>()

const isEdit = computed(() => props.sale != null)

const form = ref<SaleRecordPayload>({
  symbol: '',
  sale_date: today(),
  grams: 1,
  price_per_gram: 0,
  fee: 0,
  channel: '',
  note: ''
})

const rules: FormRules = {
  symbol: [{ required: true, message: '请选择或输入品种', trigger: 'change' }],
  sale_date: [{ required: true, message: '请选择卖出日期', trigger: 'change' }],
  grams: [{ required: true, message: '请输入卖出克数', trigger: 'blur' }],
  price_per_gram: [{ required: true, message: '请输入卖出单价', trigger: 'blur' }]
}

const canDerive = computed(() => (amount.value ?? 0) > 0 && (form.value.grams ?? 0) > 0)

const derivedHint = computed(() => {
  if (!canDerive.value) return '填总金额 + 克数可反推单价'
  return `≈ ${formatPrice((amount.value as number) / (form.value.grams as number))} /克`
})

function derivePrice() {
  if (!canDerive.value) return
  form.value.price_per_gram = Number(
    ((amount.value as number) / (form.value.grams as number)).toFixed(2)
  )
}

function fillAll() {
  if (props.availableGrams && props.availableGrams > 0) {
    form.value.grams = props.availableGrams
  }
}

function resetForm() {
  const source = props.sale
  amount.value = undefined
  if (source) {
    form.value = {
      symbol: source.symbol,
      sale_date: source.sale_date,
      grams: source.grams,
      price_per_gram: source.price_per_gram,
      fee: source.fee,
      channel: source.channel,
      note: source.note
    }
  } else {
    form.value = {
      symbol: props.defaultSymbol,
      sale_date: today(),
      grams: props.defaultGrams && props.defaultGrams > 0 ? props.defaultGrams : 1,
      price_per_gram: props.defaultPrice && props.defaultPrice > 0 ? props.defaultPrice : 0,
      fee: 0,
      channel: '',
      note: ''
    }
  }
  formRef.value?.clearValidate()
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    const payload: SaleRecordPayload = { ...form.value }
    if (isEdit.value && props.sale) {
      await portfolioApi.updateSale(props.sale.id, payload)
      ElMessage.success('已更新')
    } else {
      await portfolioApi.createSale(payload)
      ElMessage.success('已记录卖出')
    }
    emit('saved')
    emit('update:modelValue', false)
  } catch {
    // 错误提示（含超卖等 400）已由 request 拦截器统一处理
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.sale-tip {
  margin-bottom: 16px;
  line-height: 1.7;
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
