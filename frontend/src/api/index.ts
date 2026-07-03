import axios from 'axios'
import type { RoutePlanRequest, RoutePlanResponse, FeedbackRequest } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// ---- 路线规划 ----

export async function planRoute(req: RoutePlanRequest): Promise<RoutePlanResponse> {
  const { data } = await api.post<RoutePlanResponse>('/routes/plan', req)
  return data
}

export async function getRoute(routeId: string): Promise<RoutePlanResponse> {
  throw new Error(`GET route is not implemented by the backend yet: ${routeId}`)
}

export async function submitFeedback(
  routeId: string,
  feedback: FeedbackRequest
): Promise<void> {
  // 当前后端还没有 feedback endpoint；先保持前端本地可提交，不阻断规划主流程。
  console.info('feedback captured locally', { routeId, feedback })
}

// ---- SSE 流式 ----

export function subscribeToStream(
  sessionId: string,
  onProgress: (phase: string, message: string) => void,
  onComplete: (route: RoutePlanResponse) => void,
  onError: (err: Error) => void,
): EventSource {
  void onProgress
  void onComplete
  void onError
  throw new Error(`SSE stream is not implemented by the backend yet: ${sessionId}`)
}

// ---- POI 搜索 ----

export async function searchPoi(q: string, district?: string, category?: string) {
  throw new Error(`POI search is not implemented by the backend yet: ${q} ${district ?? ''} ${category ?? ''}`)
}