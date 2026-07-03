import { computed, ref } from 'vue'
import type { RoutePlanRequest, RoutePlanResponse, RoutePlanResult } from '../types'
import { planRoute } from '../api'

/**
 * 路线状态管理 composable
 */
export function useRoutePlan() {
  const loading = ref(false)
  const currentRoute = ref<RoutePlanResponse | null>(null)
  const selectedResult = ref<RoutePlanResult | null>(null)
  const history = ref<RoutePlanResponse[]>([])
  const error = ref<string | null>(null)

  const routeResults = computed(() => currentRoute.value?.route_results ?? [])
  const presentation = computed(() => currentRoute.value?.presentation ?? null)

  async function submitQuery(request: RoutePlanRequest) {
    const query = request.query.trim()
    if (!query) {
      error.value = '请输入路线需求'
      return
    }

    loading.value = true
    error.value = null
    try {
      const response = await planRoute({ ...request, query })
      currentRoute.value = response
      selectedResult.value = response.route_results[0] ?? null
      history.value.unshift(response)
    } catch (err) {
      const message = err instanceof Error ? err.message : '路线规划失败'
      error.value = message
      currentRoute.value = null
      selectedResult.value = null
    } finally {
      loading.value = false
    }
  }

  function selectResult(result: RoutePlanResult) {
    selectedResult.value = result
  }

  return {
    loading,
    currentRoute,
    selectedResult,
    routeResults,
    presentation,
    history,
    error,
    submitQuery,
    selectResult,
  }
}