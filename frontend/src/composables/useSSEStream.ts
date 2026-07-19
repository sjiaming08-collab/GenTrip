import { ref } from 'vue'
import type { RoutePlanResponse, SSEProgressEvent } from '../types'
import { cancelPlanRun, subscribeToStream } from '../api'

/**
 * SSE 流式进度 composable — 对接后端 GET /routes/plan/stream
 */
export function useSSEStream() {
  const currentPhase = ref('idle')
  const isStreaming = ref(false)
  const routeResult = ref<RoutePlanResponse | null>(null)
  const error = ref<string | null>(null)
  let source: EventSource | null = null
  let activeRunId: string | null = null

  function stopStream() {
    source?.close()
    source = null
    isStreaming.value = false
  }

  async function cancelStream() {
    if (activeRunId) {
      try {
        await cancelPlanRun(activeRunId)
      } catch {
        // The stream can still complete after a racing terminal update.
      }
    }
    stopStream()
  }

  async function startStream(query: string, sessionId: string | null) {
    stopStream()
    error.value = null
    isStreaming.value = true
    try {
      const subscription = await subscribeToStream(
        { query, session_id: sessionId ?? undefined },
        (event: SSEProgressEvent) => {
          currentPhase.value = event.phase
          activeRunId = event.run_id || activeRunId
        },
        (route: RoutePlanResponse) => {
          routeResult.value = route
          activeRunId = null
          stopStream()
        },
        (err: Error) => {
          error.value = err.message
          stopStream()
        },
      )
      source = subscription.source
      activeRunId = subscription.runId
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'SSE 启动失败'
      stopStream()
    }
  }

  return {
    currentPhase,
    isStreaming,
    routeResult,
    error,
    startStream,
    stopStream,
    cancelStream,
  }
}
