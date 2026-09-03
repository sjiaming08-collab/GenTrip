// ---- 后端 DTO 对应 TypeScript 类型 ----

export interface GeoPoint {
  lat: number
  lng: number
}

export interface RoutePlanRequest {
  query: string
  tenant_id?: string
  user_id?: string
  lat?: number
  lng?: number
  session_id?: string
  idempotency_key?: string
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
  travel_source?: string
  travel_estimated?: boolean
  queue_wait_min: number
  opening_hours_text?: string | null
  slot_id?: string | null
  slot_role?: 'anchor' | 'meal' | 'rest' | 'optional' | null
  slot_source?: 'explicit' | 'inferred' | 'policy' | null
  slot_time_window?: { start?: string | null; end?: string | null } | null
}

export interface RouteLeg {
  from_poi_id: string
  to_poi_id: string
  mode: 'walking' | 'cycling' | 'transit' | 'driving'
  distance_m: number
  duration_min: number
  cost_per_person: number
  source: string
  estimated: boolean
  confidence: 'low' | 'medium' | 'high'
  fallback_used: boolean
  selection_reason: string
}

export interface RoutePlan {
  plan_id: string
  plan_name: string
  summary: string
  stops: RouteStop[]
  total_duration_min: number
  estimated_cost_per_person: number
  legs: RouteLeg[]
  blueprint_id?: string | null
  style?: 'balanced' | 'experiential' | null
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

export type ReplyType = 'route' | 'multi_route' | 'diff' | 'degraded_route' | 'reject' | 'clarification' | 'infeasible'

export interface AgentReplyMeta {
  plan_path?: string | null
  assumptions: Assumption[]
  relaxed_constraints: string[]
  degraded: boolean
  next_suggested_user_moves: string[]
  phase_log: PhaseLogEntry[]
  llm_calls: LlmCall[]
  tool_calls?: Record<string, unknown>[]
  data_sources?: string[]
  degraded_reasons?: string[]
  token_usage: TokenUsage
  debug_trace_id?: string | null
  planning_decision?: Record<string, unknown> | null
  pending_change?: Record<string, unknown> | null
  rejected_change?: Record<string, unknown> | null
  compiled_constraints?: Record<string, unknown> | null
  active_policies?: Record<string, unknown>[]
  dropped_policies?: Record<string, unknown>[]
  blueprint_feasibility?: Record<string, unknown>[]
  planning_failures?: Record<string, unknown>[]
  repair_actions?: Record<string, unknown>[]
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
  turn_id?: string | null
  run_status: string
  plan_path?: string | null
  assumptions: Assumption[]
  route_results: RoutePlanResult[]
  current_phase: string
  planning_outcome: string
  diff_result?: RoutePlanDiff | null
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
  tenant_id?: string
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
  diff_result?: RoutePlanDiff | null
  assistant_message?: string
  ts: string
}

/** Immutable route output attached to the assistant turn that produced it. */
export interface RouteTurnSnapshot {
  snapshot_id: string
  turn_id?: string | null
  run_id?: string | null
  session_id?: string | null
  user_query?: string
  created_at?: string
  reply_type: ReplyType
  route_results: RoutePlanResult[]
  assumptions: Assumption[]
  presentation?: Presentation | null
  degraded: boolean
  next_suggested_user_moves: string[]
  diff_change_count: number
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
  pending_change?: Record<string, unknown> | null
  rejected_change?: Record<string, unknown> | null
}

export interface SessionListItem {
  session_id: string
  title: string
  dialog_summary: string
  turn_count: number
  route_count: number
  updated_at?: string | null
}

export interface PlanRunStatus {
  run_id: string
  session_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | string
  error_code?: string | null
  result?: RoutePlanResponse | null
}

export interface AuthSession {
  session_id: string
  tenant_id: string
  created_at: string
  expires_at: string
  revoked_at?: string | null
  current: boolean
}

export interface TenantMember {
  user_id: string
  email: string
  display_name: string
  role: 'owner' | 'member'
}

export interface AuditEvent {
  event_id: number
  tenant_id: string
  actor_user_id?: string | null
  action: string
  target_type: string
  target_id?: string | null
  data: Record<string, unknown>
  created_at: string
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
