import axios from 'axios'
import type { RoutePlanRequest, RoutePlanResponse, FeedbackRequest, SessionDetail, SessionListItem, SSEProgressEvent } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

const PLAN_REQUEST_TIMEOUT_MS = 120000

// ---- 路线规划 ----

export async function planRoute(req: RoutePlanRequest): Promise<RoutePlanResponse> {
  const { data } = await api.post<RoutePlanResponse>('/routes/plan', req, {
    timeout: PLAN_REQUEST_TIMEOUT_MS,
  })
  return data
}

export async function getRoute(routeId: string): Promise<RoutePlanResponse> {
  throw new Error(`GET route is not implemented by the backend yet: ${routeId}`)
}

export async function submitFeedback(feedback: FeedbackRequest): Promise<void> {
  await api.post('/routes/feedback', feedback)
}

export async function cancelPlanRun(runId: string): Promise<void> {
  await api.post(`/routes/plan/runs/${runId}/cancel`)
}

export async function listSessions(userId: string, limit = 30): Promise<SessionListItem[]> {
  const { data } = await api.get<{ sessions: SessionListItem[] }>('/sessions', {
    params: { user_id: userId, limit },
  })
  return data.sessions
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const { data } = await api.get<SessionDetail>(`/sessions/${sessionId}`)
  return data
}

export async function updateSessionTitle(sessionId: string, title: string): Promise<SessionDetail> {
  const { data } = await api.patch<SessionDetail>(`/sessions/${sessionId}`, { title })
  return data
}

// ---- SSE 流式 ----

export function subscribeToStream(
  request: RoutePlanRequest,
  onProgress: (event: SSEProgressEvent) => void,
  onComplete: (route: RoutePlanResponse) => void,
  onError: (err: Error) => void,
): EventSource {
  const params = new URLSearchParams()
  params.set('query', request.query)
  if (request.session_id) params.set('session_id', request.session_id)
  if (request.user_id) params.set('user_id', request.user_id)
  if (request.lat !== undefined) params.set('lat', String(request.lat))
  if (request.lng !== undefined) params.set('lng', String(request.lng))

  const url = `/api/v1/routes/plan/stream?${params.toString()}`
  const source = new EventSource(url)

  source.addEventListener('phase', (event) => {
    try {
      onProgress(JSON.parse(event.data) as SSEProgressEvent)
    } catch {
      // Ignore malformed transient events and wait for the persisted final result.
    }
  })

  source.addEventListener('complete', (event) => {
    try {
      const data = JSON.parse(event.data) as { status: string; response?: RoutePlanResponse }
      if (data.response) {
        onComplete(data.response)
      } else {
        onError(new Error(`plan run ${data.status}`))
      }
    } catch {
      onError(new Error('invalid completion event'))
    } finally {
      source.close()
    }
  })

  source.addEventListener('error', () => {
    // EventSource auto-reconnects; only fire onError if not closed intentionally
    if (source.readyState === EventSource.CLOSED) {
      onError(new Error('SSE connection closed'))
    }
  })

  return source
}

// ---- POI 搜索 ----

export async function searchPoi(q: string, district?: string, category?: string) {
  throw new Error(`POI search is not implemented by the backend yet: ${q} ${district ?? ''} ${category ?? ''}`)
}
