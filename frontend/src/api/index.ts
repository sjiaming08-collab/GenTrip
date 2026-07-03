import axios from 'axios'
import type { RoutePlanRequest, RoutePlanResponse, FeedbackRequest } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// ---- 路线规划 ----

export async function planRoute(req: RoutePlanRequest): Promise<RoutePlanResponse> {
  // TODO: 实现 POST /api/v1/routes/plan
  throw new Error('Not implemented')
}

export async function getRoute(routeId: string): Promise<RoutePlanResponse> {
  // TODO: 实现 GET /api/v1/routes/{id}
  throw new Error('Not implemented')
}

export async function submitFeedback(
  routeId: string,
  feedback: FeedbackRequest
): Promise<void> {
  // TODO: 实现 POST /api/v1/routes/{id}/feedback
  throw new Error('Not implemented')
}

// ---- SSE 流式 ----

export function subscribeToStream(
  sessionId: string,
  onProgress: (phase: string, message: string) => void,
  onComplete: (route: RoutePlanResponse) => void,
  onError: (err: Error) => void,
): EventSource {
  // TODO: 实现 GET /api/v1/routes/stream/{sessionId} (SSE)
  throw new Error('Not implemented')
}

// ---- POI 搜索 ----

export async function searchPoi(q: string, district?: string, category?: string) {
  // TODO: 实现 GET /api/v1/poi/search
  throw new Error('Not implemented')
}
