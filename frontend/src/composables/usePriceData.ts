import { ref, onMounted, onUnmounted } from 'vue'
import { priceApi } from '@/api/modules/gold'
import type { DashboardResponse } from '@/api/modules/gold'

const POLL_INTERVAL = 10000

export function usePriceData(options?: { autoStart?: boolean }) {
  const autoStart = options?.autoStart ?? true
  const dashboard = ref<DashboardResponse | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  const fetchDashboard = async () => {
    loading.value = true
    try {
      dashboard.value = await priceApi.getDashboard()
    } catch {
      // 错误已在 request 拦截器中处理
    } finally {
      loading.value = false
    }
  }

  const startPolling = () => {
    fetchDashboard()
    timer = setInterval(fetchDashboard, POLL_INTERVAL)
  }

  const stopPolling = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  if (autoStart) {
    onMounted(startPolling)
  }
  onUnmounted(stopPolling)

  return { dashboard, loading, fetchDashboard, startPolling, stopPolling }
}
