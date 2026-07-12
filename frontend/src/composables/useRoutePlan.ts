import { computed, ref } from 'vue'
import { cancelPlanRun, subscribeToStream } from '../api'
import type { RoutePlanRequest, RoutePlanResponse, RoutePlanResult, SSEProgressEvent } from '../types'

/** Route state managed through the durable SSE planning run. */
export function useRoutePlan() {
  const loading = ref(false)
  const currentPhase = ref('idle')
  const currentRoute = ref<RoutePlanResponse | null>(null)
  const selectedResult = ref<RoutePlanResult | null>(null)
  const history = ref<RoutePlanResponse[]>([])
  const error = ref<string | null>(null)
  let source: EventSource | null = null
  let activeRunId: string | null = null

  const routeResults = computed(() => currentRoute.value?.route_results ?? [])
  const presentation = computed(() => currentRoute.value?.presentation ?? null)

  async function submitQuery(request: RoutePlanRequest) {
    const query = request.query.trim()
    if (!query) {
      error.value = '请输入路线需求'
      return
    }

    source?.close()
    loading.value = true
    currentPhase.value = 'turn_orchestrate'
    error.value = null
    activeRunId = null

    await new Promise<void>((resolve) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        source = null
        activeRunId = null
        loading.value = false
        resolve()
      }

      source = subscribeToStream(
        { ...request, query },
        (event: SSEProgressEvent) => {
          currentPhase.value = event.phase
          activeRunId = event.run_id || activeRunId
        },
        (response: RoutePlanResponse) => {
          currentRoute.value = response
          selectedResult.value = response.route_results[0] ?? null
          history.value.unshift(response)
          finish()
        },
        (streamError: Error) => {
          error.value = streamError.message
          currentRoute.value = null
          selectedResult.value = null
          finish()
        },
      )
    })
  }

  function cancelPlanning() {
    const runId = activeRunId
    source?.close()
    source = null
    activeRunId = null
    loading.value = false
    currentPhase.value = 'idle'
    if (runId) {
      void cancelPlanRun(runId)
    }
  }

  function selectResult(result: RoutePlanResult) {
    selectedResult.value = result
  }

  function restoreRoute(response: RoutePlanResponse) {
    currentRoute.value = response
    selectedResult.value = response.route_results[0] ?? null
    currentPhase.value = response.current_phase || 'completed'
    error.value = null
  }

  function resetPlanningState() {
    source?.close()
    source = null
    activeRunId = null
    loading.value = false
    currentPhase.value = 'idle'
    currentRoute.value = null
    selectedResult.value = null
    error.value = null
  }

  return {
    loading,
    currentPhase,
    currentRoute,
    selectedResult,
    routeResults,
    presentation,
    history,
    error,
    submitQuery,
    cancelPlanning,
    resetPlanningState,
    selectResult,
    restoreRoute,
  }
}
