import type { SSEProgressEvent } from '../types'

type PhasePresentation = {
  title: string
  description: string
}

const PHASES: Record<string, PhasePresentation> = {
  runtime: { title: '准备任务', description: '正在创建可恢复的规划任务。' },
  turn_orchestrate: { title: '理解本轮诉求', description: '正在结合当前路线判断这是新规划还是局部调整。' },
  replan_parse: { title: '拆解调整要求', description: '正在识别要增加、删除或替换的内容。' },
  lock_confirmed: { title: '保护已确认行程', description: '正在保留未要求修改的路线站点。' },
  partial_retrieval: { title: '检索替换候选', description: '正在为变更位置检索匹配的 POI。' },
  local_optimize: { title: '局部重排路线', description: '正在重新安排受影响的站点与顺序。' },
  validate_delta: { title: '校验调整结果', description: '正在检查时间、预算和约束是否仍可执行。' },
  render_diff: { title: '生成变更说明', description: '正在整理本次路线修改与原因。' },
  constraint_extract: { title: '提取出行约束', description: '正在识别区域、预算、时间和偏好。' },
  planning_decision: { title: '评估可行性', description: '正在根据时间与交通估算判断是否可执行。' },
  route_bundle_search: { title: '检查路线复用', description: '正在检查是否有可复用的高质量路线方案。' },
  geo_resolve: { title: '确定活动范围', description: '正在解析区域和附近范围。' },
  poi_retrieve: { title: '检索地点', description: '正在从本地 POI 数据中筛选候选地点。' },
  route_generate: { title: '生成候选路线', description: '正在组合地点、停留时间与交通估算。' },
  route_validate: { title: '校验候选路线', description: '正在过滤不满足预算、时间或偏好的方案。' },
  auto_relax: { title: '尝试温和放宽', description: '正在仅在必要时放宽非硬性条件。' },
  route_evaluate: { title: '排序候选路线', description: '正在综合偏好、可行性和路线质量评分。' },
  route_bundle_ingest: { title: '保存路线经验', description: '正在记录可复用的确定性路线结果。' },
  route_present: { title: '整理路线建议', description: '正在生成易读的路线说明。' },
  dialog_summary: { title: '更新会话记忆', description: '正在保存本轮对话与偏好摘要。' },
  complete: { title: '完成规划', description: '路线结果已准备好。' },
}

export function presentPhase(phase: string): PhasePresentation {
  return PHASES[phase] ?? { title: phase.split('_').join(' '), description: '正在执行此规划步骤。' }
}

export function presentStatus(status: string | undefined): string {
  if (status === 'completed' || status === 'success') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  if (status === 'degraded') return '已降级完成'
  return '进行中'
}

export function nextPhase(event: SSEProgressEvent | undefined): string | null {
  if (!event || !['completed', 'success'].includes(event.status || '')) return null
  const replan = event.data?.turn_mode === 'replan'
  const next: Record<string, string | undefined> = replan
    ? {
        turn_orchestrate: 'replan_parse', replan_parse: 'lock_confirmed', lock_confirmed: 'partial_retrieval',
        partial_retrieval: 'local_optimize', local_optimize: 'validate_delta', validate_delta: 'render_diff',
      }
    : {
        turn_orchestrate: 'constraint_extract', constraint_extract: 'planning_decision', planning_decision: 'route_bundle_search',
        route_bundle_search: 'geo_resolve', geo_resolve: 'poi_retrieve', poi_retrieve: 'route_generate',
        route_generate: 'route_validate', route_validate: 'route_evaluate', route_evaluate: 'route_bundle_ingest',
        route_bundle_ingest: 'route_present', route_present: 'dialog_summary',
      }
  return next[event.phase] ?? null
}

export function stageOutcome(event: SSEProgressEvent): string {
  const phase = event.phase
  if (phase === 'constraint_extract') {
    const constraints = event.data?.extracted_constraints as Record<string, unknown> | undefined
    if (constraints) {
      const parts = [
        constraints.district ? `区域 ${constraints.district}` : '',
        constraints.budget_per_person ? `人均 ${constraints.budget_per_person} 元` : '',
        constraints.time_budget_minutes ? `时长 ${constraints.time_budget_minutes} 分钟` : '',
        constraints.start_at ? `出发 ${constraints.start_at}` : '',
        constraints.return_by ? `最晚返回 ${constraints.return_by}` : '',
        Array.isArray(constraints.preferred_cuisines) && constraints.preferred_cuisines.length
          ? `偏好 ${constraints.preferred_cuisines.join('、')}` : '',
        Array.isArray(constraints.excluded_categories) && constraints.excluded_categories.length
          ? `避开 ${constraints.excluded_categories.join('、')}` : '',
      ].filter(Boolean)
      const source = event.data?.constraint_source === 'llm' ? '模型解析' : '规则兜底'
      return parts.length ? `${source}：${parts.join('；')}` : event.summary || presentPhase(phase).description
    }
  }
  if (phase === 'turn_orchestrate') {
    const mode = event.data?.turn_mode === 'replan' ? '基于当前路线调整' : '新路线规划'
    return `已识别为${mode}。`
  }
  if (phase === 'poi_retrieve') return event.summary || '已完成候选地点筛选。'
  return event.summary || presentPhase(phase).description
}
