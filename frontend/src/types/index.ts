// ---- 后端 DTO 对应 TypeScript 类型 ----

export interface GeoPoint {
  lat: number
  lng: number
}

export interface PoiSummary {
  id: string
  name: string
  category: string
  overall_rating: number
  avg_price_per_person: number
  address: string
  latitude: number
  longitude: number
  detail_url?: string
  cover_image_url?: string
  phone_number?: string
}

export interface ItineraryStop {
  sequence: number
  poi: PoiSummary
  arrival_time: string
  departure_time: string
  visit_duration_min: number
  travel_time_from_prev_min: number
  travel_mode: 'WALK' | 'TRANSIT' | 'BIKE' | 'TAXI' | 'START'
  ai_tip?: string
  estimated_queue_min?: number
  reservation_url?: string
}

export interface RouteMetadata {
  total_duration_min: number
  total_travel_time_min: number
  total_pois: number
  average_poi_score: number
  start_time: string
  end_time: string
  weather_note?: string
}

export interface RoutePlanResponse {
  route_id: string
  source: 'CACHE_HIT' | 'CACHE_ADAPTED' | 'FRESH_GENERATED'
  plan_name: string
  stops: ItineraryStop[]
  metadata: RouteMetadata
  map_deep_link?: string
}

export interface RoutePlanRequest {
  query: string
  user_id?: string
  lat?: number
  lng?: number
}

export interface FeedbackRequest {
  route_id: string
  overall_score: number
  poi_ratings?: Record<string, number>
  comments?: string
}

export interface SSEProgressEvent {
  phase: string
  message: string
}
