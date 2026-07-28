import { ref, onMounted, onUnmounted } from 'vue'
import { priceApi } from '@/api/modules/gold'
import type { PriceSnapshot } from '@/api/modules/gold'

const DEFAULT_SYMBOL = 'gds_AUTD'
const POLL_INTERVAL = 10000

export function usePriceData(symbol = DEFAULT_SYMBOL) {
  const snapshot = ref<PriceSnapshot | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  const fetchSnapshot = async () => {
    loading.value = true
    try {
      snapshot.value = await priceApi.getSnapshot(symbol)
    } catch {
      // 错误已在 request 拦截器中处理
    } finally {
      loading.value = false
    }
  }

  const startPolling = () => {
    fetchSnapshot()
    timer = setInterval(fetchSnapshot, POLL_INTERVAL)
  }

  const stopPolling = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(startPolling)
  onUnmounted(stopPolling)

  return { snapshot, loading, fetchSnapshot }
}
