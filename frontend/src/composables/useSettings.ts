import { ref, reactive } from 'vue'

export function useSettingsGroup<T>(fetchFn: () => Promise<T>, updateFn: (data: T) => Promise<T>) {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  const load = async () => {
    loading.value = true
    try {
      data.value = await fetchFn()
    } catch {
      // 错误已在 request 拦截器中处理
    } finally {
      loading.value = false
    }
  }

  const save = async () => {
    if (!data.value) return
    saving.value = true
    try {
      await updateFn(data.value)
      ElMessage.success('保存成功')
    } catch {
      // 错误已在 request 拦截器中处理
    } finally {
      saving.value = false
    }
  }

  return reactive({ data, loading, saving, load, save })
}
