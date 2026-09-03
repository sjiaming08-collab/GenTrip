import type { RoutePlanResponse, RouteTurnSnapshot, SessionTurn } from '../types'

export function snapshotFromResponse(response: RoutePlanResponse, userQuery = ''): RouteTurnSnapshot {
  return {
    snapshot_id: response.turn_id || response.run_id,
    turn_id: response.turn_id,
    run_id: response.run_id,
    session_id: response.session_id,
    user_query: userQuery,
    created_at: new Date().toISOString(),
    reply_type: response.reply_type,
    route_results: response.route_results,
    assumptions: response.assumptions,
    presentation: response.presentation,
    degraded: response.reply_type === 'degraded_route' || Boolean(response.meta.degraded),
    next_suggested_user_moves: response.meta.next_suggested_user_moves ?? [],
    diff_change_count: response.diff_result?.changes.filter((item) => item.type !== 'unchanged').length ?? 0,
  }
}

export function snapshotFromTurn(turn: SessionTurn, sessionId: string): RouteTurnSnapshot {
  return {
    snapshot_id: turn.turn_id,
    turn_id: turn.turn_id,
    session_id: sessionId,
    user_query: turn.user_query,
    created_at: turn.ts,
    reply_type: turn.reply_type,
    route_results: turn.route_results,
    assumptions: turn.assumptions,
    presentation: turn.presentation,
    degraded: turn.reply_type === 'degraded_route',
    next_suggested_user_moves: [],
    diff_change_count: turn.diff_result?.changes.filter((item) => item.type !== 'unchanged').length ?? 0,
  }
}
