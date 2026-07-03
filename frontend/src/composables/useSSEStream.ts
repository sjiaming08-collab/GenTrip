import { ref } from 'vue'
import type { RoutePlanResponse } from '../types'
import { subscribeToStream } from '../api'

/**
 * SSE 流式进度 composable。当前后端还没有 SSE endpoint，保留可编译的调用边界。
 */
export function useSSEStream() {
  const currentPhase = ref('idle')
  const isStreaming = ref(false)
  const routeResult = ref<RoutePlanResponse | null>(null)
  const error = ref<string | null>(null)
  let source: EventSource | null = null

  function stopStream() {
    source?.close()
    source = null
    isStreaming.value = false
  }

  function startStream(sessionId: string) {
    stopStream()
    error.value = null
    isStreaming.value = true
    try {
      source = subscribeToStream(
        sessionId,
        (phase) => {
          currentPhase.value = phase
        },
        (route) => {
          routeResult.value = route
          stopStream()
        },
        (err) => {
          error.value = err.message
          stopStream()
        },
      )
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
  }
}