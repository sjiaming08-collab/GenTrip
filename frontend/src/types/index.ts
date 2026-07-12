// ---- 后端 DTO 对应 TypeScript 类型 ----

export interface GeoPoint {
  lat: number
  lng: number
}

export interface RoutePlanRequest {
  query: string
  user_id?: string
  lat?: number
  lng?: number
  session_id?: string
}

export interface Assumption {
  slot: string
  assumed_value: string
  source: string
  message: string
  overridable?: boolean
}

export interface RouteStop {
  sequence: number
  poi_id: string
  poi_name: string
  category: string
  arrival_time: string
  departure_time: string
  visit_duration_min: number
  travel_time_from_prev_min: number
  queue_wait_min: number
}

export interface RoutePlan {
  plan_id: string
  plan_name: string
  summary: string
  stops: RouteStop[]
  total_duration_min: number
  estimated_cost_per_person: number
}

export interface RouteScores {
  execution: number
  quality: number
  final: number
}

export interface RoutePlanResult {
  route: RoutePlan
  source: 'BUNDLE_HIT' | 'BUNDLE_ADAPTED' | 'COLD_GENERATED' | 'DEGRADED'
  bundle_id?: string | null
  rank: number
  scores: RouteScores
}

export interface Presentation {
  title: string
  summary: string
  highlights: string[]
}

export type ReplyType = 'route' | 'multi_route' | 'diff' | 'degraded_route' | 'reject'

export interface AgentReplyMeta {
  plan_path?: string | null
  assumptions: Assumption[]
  relaxed_constraints: string[]
  degraded: boolean
  next_suggested_user_moves: string[]
  phase_log: PhaseLogEntry[]
  llm_calls: LlmCall[]
  token_usage: TokenUsage
  debug_trace_id?: string | null
}

export interface PhaseLogEntry {
  phase: string
  status: string
  ts: string
  summary?: string
}

export interface LlmCall {
  operation: string
  provider: string
  model?: string | null
  status: 'success' | 'skipped' | 'failed' | 'fallback'
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  latency_ms: number
  fallback_used: boolean
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  call_count: number
}

export interface AgentReplyResponse {
  reply_type: ReplyType
  run_id: string
  session_id?: string | null
  structured: RoutePlanResult[]
  presentation?: Presentation | null
  meta: AgentReplyMeta
}

export interface RoutePlanResponse extends AgentReplyResponse {
  run_status: string
  plan_path?: string | null
  assumptions: Assumption[]
  route_results: RoutePlanResult[]
  current_phase: string
}

// ---- Diff types for Replan ----

export interface DiffEntry {
  type: 'added' | 'removed' | 'replaced' | 'unchanged'
  sequence: number
  old_poi_name?: string | null
  new_poi_name?: string | null
  reason?: string
}

export interface RoutePlanDiff {
  original_plan_id: string
  new_plan_id: string
  changes: DiffEntry[]
  summary: string
}

// ---- Feedback (aligned with backend) ----

export interface FeedbackRequest {
  session_id: string
  action: 'confirm' | 'reject_poi' | 'rate' | 'overturn_assumption'
  poi_id?: string | null
  route_id?: string | null
  score?: number | null
  comment?: string | null
  overturned_assumption?: string | null
}

export interface SessionTurn {
  turn_id: string
  user_query: string
  reply_type: ReplyType
  route_results: RoutePlanResult[]
  assumptions: Assumption[]
  presentation?: Presentation | null
  assistant_message?: string
  ts: string
}

export interface SessionDetail {
  session_id: string
  title: string
  turn_count: number
  mode: string
  current_route?: RoutePlan | null
  dialog_summary: string
  assumptions: Assumption[]
  recent_turns: SessionTurn[]
  turns: SessionTurn[]
  latest_response?: RoutePlanResponse | null
}

export interface SessionListItem {
  session_id: string
  title: string
  dialog_summary: string
  turn_count: number
  route_count: number
  updated_at?: string | null
}

// ---- SSE ----

export interface SSEProgressEvent {
  event_id?: number
  run_id?: string
  phase: string
  status?: string
  summary?: string
  data?: Record<string, unknown>
}
