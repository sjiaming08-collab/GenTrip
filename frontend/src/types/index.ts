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

export interface RoutePlanResponse {
  run_id: string
  run_status: string
  plan_path?: string | null
  assumptions: Assumption[]
  route_results: RoutePlanResult[]
  presentation?: Presentation | null
  current_phase: string
}

export interface FeedbackRequest {
  route_id: string
  overall_score: number
  comments?: string
}

export interface SSEProgressEvent {
  phase: string
  message: string
}