import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RouteTurnCard from './RouteTurnCard.vue'
import type { RouteTurnSnapshot } from '../types'

const snapshot: RouteTurnSnapshot = {
  snapshot_id: 'turn-1',
  turn_id: 'turn-1',
  session_id: 'session-1',
  user_query: '中午想吃正餐',
  reply_type: 'diff',
  route_results: [{
    route: {
      plan_id: 'plan-1',
      plan_name: '西湖一日路线',
      summary: '可执行路线',
      stops: [],
      legs: [],
      total_duration_min: 480,
      estimated_cost_per_person: 180,
    },
    source: 'COLD_GENERATED',
    rank: 1,
    scores: { execution: 0.8, quality: 0.8, final: 0.8 },
  }],
  assumptions: [],
  presentation: { title: '路线修订', summary: '已替换午餐', highlights: [] },
  degraded: false,
  next_suggested_user_moves: [],
  diff_change_count: 1,
}

describe('RouteTurnCard', () => {
  it('keeps a historical route as a compact expandable version card', async () => {
    const wrapper = mount(RouteTurnCard, {
      props: { snapshot, expanded: false, isLatest: false },
      global: { stubs: { RouteCanvas: true, FeedbackPanel: true } },
    })

    expect(wrapper.text()).toContain('历史方案')
    expect(wrapper.text()).toContain('中午想吃正餐')
    expect(wrapper.text()).toContain('调整 1 处')
    expect(wrapper.text()).not.toContain('路线修订')

    await wrapper.get('.snapshot-header').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })

  it('shows route content when expanded and feedback only on latest version', () => {
    const wrapper = mount(RouteTurnCard, {
      props: { snapshot, expanded: true, isLatest: true },
      global: { stubs: { RouteCanvas: true, FeedbackPanel: true } },
    })

    expect(wrapper.text()).toContain('当前方案')
    expect(wrapper.text()).toContain('路线修订')
    expect(wrapper.findComponent({ name: 'FeedbackPanel' }).exists()).toBe(true)
  })
})
