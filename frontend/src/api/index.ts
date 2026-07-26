import axios from 'axios'
import type {
  AuditEvent,
  AuthSession,
  FeedbackRequest,
  PlanRunStatus,
  RoutePlanRequest,
  RoutePlanResponse,
  SSEProgressEvent,
  SessionDetail,
  SessionListItem,
  TenantMember,
} from '../types'

export type AuthIdentity = {
  access_token: string
  token_type: string
  user: { user_id: string; email: string; display_name: string }
  tenant: { tenant_id: string; name: string; role: 'owner' | 'member' }
}

export type Workspace = AuthIdentity['tenant']

type PlanRunStartedResponse = {
  run_id: string
  session_id: string
  status: string
}

export type StreamSubscription = {
  source: EventSource
  runId: string
  sessionId: string
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,
})

const PLAN_REQUEST_TIMEOUT_MS = 120000

export async function getHealth(): Promise<{ auth_enabled: boolean; llm_enabled?: boolean; llm_model?: string | null }> {
  const { data } = await api.get<{ auth_enabled: boolean; llm_enabled?: boolean; llm_model?: string | null }>('/health')
  return data
}

export async function getCurrentUser(): Promise<AuthIdentity> {
  const { data } = await api.get<AuthIdentity>('/auth/me')
  return data
}

export async function login(email: string, password: string): Promise<AuthIdentity> {
  const { data } = await api.post<AuthIdentity>('/auth/login', { email, password })
  return data
}

export async function register(email: string, password: string, displayName: string, tenantName: string): Promise<AuthIdentity> {
  const { data } = await api.post<AuthIdentity>('/auth/register', {
    email,
    password,
    display_name: displayName,
    tenant_name: tenantName,
  })
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}

export async function listWorkspaces(): Promise<Workspace[]> {
  const { data } = await api.get<{ workspaces: Workspace[] }>('/auth/workspaces')
  return data.workspaces
}

export async function switchWorkspace(tenantId: string): Promise<AuthIdentity> {
  const { data } = await api.post<AuthIdentity>('/auth/switch-workspace', { tenant_id: tenantId })
  return data
}

export async function listAuthSessions(limit = 20): Promise<AuthSession[]> {
  const { data } = await api.get<{ sessions: AuthSession[] }>('/auth/sessions', { params: { limit } })
  return data.sessions
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  await api.delete(`/auth/sessions/${sessionId}`)
}

export async function revokeOtherAuthSessions(): Promise<void> {
  await api.post('/auth/sessions/revoke-others')
}

export async function listTenantMembers(): Promise<TenantMember[]> {
  const { data } = await api.get<{ members: TenantMember[] }>('/tenants/current/members')
  return data.members
}

export async function addTenantMember(email: string, role: TenantMember['role']): Promise<TenantMember> {
  const { data } = await api.post<TenantMember>('/tenants/current/members', { email, role })
  return data
}

export async function updateTenantMemberRole(userId: string, role: TenantMember['role']): Promise<void> {
  await api.patch(`/tenants/current/members/${userId}`, { role })
}

export async function removeTenantMember(userId: string): Promise<void> {
  await api.delete(`/tenants/current/members/${userId}`)
}

export async function listTenantAuditEvents(limit = 50): Promise<AuditEvent[]> {
  const { data } = await api.get<{ events: AuditEvent[] }>('/tenants/current/audit-events', { params: { limit } })
  return data.events
}

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

export async function getPlanRun(runId: string, tenantId?: string): Promise<PlanRunStatus> {
  const { data } = await api.get<PlanRunStatus>(`/routes/plan/runs/${runId}`, {
    params: tenantId ? { tenant_id: tenantId } : undefined,
  })
  return data
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

export async function deleteSession(sessionId: string): Promise<void> {
  await api.delete(`/sessions/${sessionId}`)
}

// ---- SSE 流式 ----

export async function subscribeToStream(
  request: RoutePlanRequest,
  onProgress: (event: SSEProgressEvent) => void,
  onComplete: (route: RoutePlanResponse) => void,
  onError: (err: Error) => void,
): Promise<StreamSubscription> {
  let started: PlanRunStartedResponse
  try {
    const response = await api.post<PlanRunStartedResponse>('/routes/plan/runs', request, { timeout: 30000 })
    started = response.data
  } catch (reason) {
    if (axios.isAxiosError(reason) && reason.response?.status === 401) {
      throw new Error('authentication_required')
    }
    throw reason
  }
  const source = subscribeToRunEvents(started.run_id, onProgress, onComplete, onError)

  return { source, runId: started.run_id, sessionId: started.session_id }
}

export function subscribeToRunEvents(
  runId: string,
  onProgress: (event: SSEProgressEvent) => void,
  onComplete: (route: RoutePlanResponse) => void,
  onError: (err: Error) => void,
): EventSource {
  const source = new EventSource(`/api/v1/routes/plan/runs/${runId}/events`)

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
