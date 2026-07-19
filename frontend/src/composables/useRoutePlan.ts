import { computed, ref } from 'vue'
import { cancelPlanRun, getPlanRun, subscribeToRunEvents, subscribeToStream } from '../api'
import type { RoutePlanRequest, RoutePlanResponse, RoutePlanResult, SSEProgressEvent } from '../types'

const ACTIVE_RUN_STORAGE_KEY = 'gentrip-active-plan-run'

type PersistedRun = { runId: string; sessionId: string }

function saveActiveRun(runId: string, sessionId: string) {
  sessionStorage.setItem(ACTIVE_RUN_STORAGE_KEY, JSON.stringify({ runId, sessionId } satisfies PersistedRun))
}

function clearActiveRun() {
  sessionStorage.removeItem(ACTIVE_RUN_STORAGE_KEY)
}

function loadActiveRun(): PersistedRun | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(ACTIVE_RUN_STORAGE_KEY) || 'null') as PersistedRun | null
    return value?.runId && value.sessionId ? value : null
  } catch {
    clearActiveRun()
    return null
  }
}

/** Route state managed through the durable SSE planning run. */
export function useRoutePlan() {
  const loading = ref(false)
  const currentPhase = ref('idle')
  const currentRoute = ref<RoutePlanResponse | null>(null)
  const selectedResult = ref<RoutePlanResult | null>(null)
  const history = ref<RoutePlanResponse[]>([])
  const error = ref<string | null>(null)
  const runtimeEvents = ref<SSEProgressEvent[]>([])
  let source: EventSource | null = null
  const activeRunId = ref<string | null>(null)

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
    runtimeEvents.value = []
    error.value = null
    activeRunId.value = null
    clearActiveRun()

    await new Promise<void>((resolve) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        source = null
        activeRunId.value = null
        clearActiveRun()
        loading.value = false
        resolve()
      }

      void subscribeToStream(
        { ...request, query, idempotency_key: request.idempotency_key || crypto.randomUUID() },
        (event: SSEProgressEvent) => {
          runtimeEvents.value = [...runtimeEvents.value, event].slice(-120)
          currentPhase.value = event.phase
          activeRunId.value = event.run_id || activeRunId.value
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
      ).then((subscription) => {
        if (settled) {
          subscription.source.close()
          return
        }
        source = subscription.source
        activeRunId.value = subscription.runId
        saveActiveRun(subscription.runId, subscription.sessionId)
      }).catch((streamError: unknown) => {
        error.value = streamError instanceof Error ? streamError.message : '无法创建规划任务'
        finish()
      })
    })
  }

  function cancelPlanning() {
    const runId = activeRunId.value
    source?.close()
    source = null
    activeRunId.value = null
    clearActiveRun()
    loading.value = false
    currentPhase.value = 'idle'
    if (runId) {
      void cancelPlanRun(runId).catch(() => {
        // The local stream is already closed; a subsequent refresh can still inspect this run.
      })
    }
  }

  function selectResult(result: RoutePlanResult) {
    selectedResult.value = result
  }

  function restoreRoute(response: RoutePlanResponse) {
    currentRoute.value = response
    if (!runtimeEvents.value.length) {
      runtimeEvents.value = response.meta.phase_log.map((entry) => ({
        run_id: response.run_id,
        phase: String(entry.phase || 'runtime'),
        status: entry.status,
        summary: entry.summary,
        data: { phase_log_entry: entry },
      }))
    }
    selectedResult.value = response.route_results[0] ?? null
    currentPhase.value = response.current_phase || 'completed'
    error.value = null
  }

  function resetPlanningState() {
    source?.close()
    source = null
    activeRunId.value = null
    clearActiveRun()
    loading.value = false
    currentPhase.value = 'idle'
    runtimeEvents.value = []
    currentRoute.value = null
    selectedResult.value = null
    error.value = null
  }

  function applyCompletedRun(response: RoutePlanResponse) {
    currentRoute.value = response
    if (!runtimeEvents.value.length) {
      runtimeEvents.value = response.meta.phase_log.map((entry) => ({
        run_id: response.run_id,
        phase: String(entry.phase || 'runtime'),
        status: entry.status,
        summary: entry.summary,
        data: { phase_log_entry: entry },
      }))
    }
    selectedResult.value = response.route_results[0] ?? null
    if (!history.value.some((item) => item.run_id === response.run_id)) history.value.unshift(response)
    currentPhase.value = response.current_phase || 'completed'
    error.value = null
  }

  async function recoverActiveRun(): Promise<RoutePlanResponse | null> {
    const persisted = loadActiveRun()
    if (!persisted) return null

    activeRunId.value = persisted.runId
    const run = await getPlanRun(persisted.runId)
    if (run.result) {
      applyCompletedRun(run.result)
      activeRunId.value = null
      clearActiveRun()
      return run.result
    }
    if (run.status === 'failed' || run.status === 'cancelled') {
      error.value = run.error_code || `plan run ${run.status}`
      activeRunId.value = null
      clearActiveRun()
      return null
    }

    loading.value = true
    runtimeEvents.value = []
    currentPhase.value = run.status
    source?.close()
    source = subscribeToRunEvents(
      persisted.runId,
      (event) => {
        runtimeEvents.value = [...runtimeEvents.value, event].slice(-120)
        currentPhase.value = event.phase
      },
      (response) => {
        applyCompletedRun(response)
        source = null
        activeRunId.value = null
        loading.value = false
        clearActiveRun()
      },
      (streamError) => {
        error.value = streamError.message
        source = null
        activeRunId.value = null
        loading.value = false
        clearActiveRun()
      },
    )
    return null
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
    activeRunId,
    runtimeEvents,
    submitQuery,
    cancelPlanning,
    resetPlanningState,
    selectResult,
    restoreRoute,
    recoverActiveRun,
  }
}
