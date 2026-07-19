<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { addTenantMember, listAuthSessions, listTenantAuditEvents, listTenantMembers, removeTenantMember, revokeAuthSession, revokeOtherAuthSessions, updateTenantMemberRole, type AuthIdentity } from '../api'
import type { AuditEvent, AuthSession, RoutePlanResponse, SSEProgressEvent, TenantMember } from '../types'

const props = defineProps<{
  open: boolean
  identity: AuthIdentity | null
  route: RoutePlanResponse | null
  activeRunId: string | null
  events: SSEProgressEvent[]
  loading: boolean
  currentPhase: string
  llmEnabled: boolean
  llmModel: string | null
}>()
const emit = defineEmits<{ close: [] }>()
const activeTab = ref<'runtime' | 'security' | 'workspace'>('runtime')
const authSessions = ref<AuthSession[]>([])
const members = ref<TenantMember[]>([])
const auditEvents = ref<AuditEvent[]>([])
const memberEmail = ref('')
const memberRole = ref<TenantMember['role']>('member')
const busy = ref(false)
const message = ref<string | null>(null)
const loadError = ref<string | null>(null)
const isOwner = computed(() => props.identity?.tenant.role === 'owner')

const liveEvents = computed<SSEProgressEvent[]>(() => {
  if (props.events.length) return props.events
  return (props.route?.meta.phase_log ?? []).map((entry) => ({
    run_id: props.route?.run_id,
    phase: String(entry.phase || 'runtime'),
    status: entry.status,
    summary: entry.summary,
    data: { phase_log_entry: entry },
  }))
})
const latestEvent = computed(() => liveEvents.value[liveEvents.value.length - 1] || null)
const liveLlmCalls = computed(() => {
  const event = [...liveEvents.value].reverse().find((item) => Array.isArray(item.data?.llm_calls))
  return (event?.data?.llm_calls as Record<string, unknown>[] | undefined) ?? props.route?.meta.llm_calls ?? []
})
const liveToolCalls = computed(() => {
  const event = [...liveEvents.value].reverse().find((item) => Array.isArray(item.data?.tool_calls))
  return (event?.data?.tool_calls as Record<string, unknown>[] | undefined) ?? props.route?.meta.tool_calls ?? []
})
const liveUsage = computed(() => {
  const event = [...liveEvents.value].reverse().find((item) => item.data?.token_usage)
  return (event?.data?.token_usage as Record<string, number> | undefined) ?? props.route?.meta.token_usage
})

function details(event: SSEProgressEvent) {
  return Object.entries(event.data || {}).filter(([key, value]) => !['llm_calls', 'tool_calls', 'phase_log_entry'].includes(key) && value !== null && value !== undefined && value !== '' && !(Array.isArray(value) && !value.length)).slice(0, 6)
}
function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function toolName(call: Record<string, unknown>) { return String(call.operation || call.tool || call.name || call.source || 'tool_call') }
function toolStatus(call: Record<string, unknown>) { return String(call.status || call.source || 'recorded') }
function formatDate(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function selectTab(tab: typeof activeTab.value) { activeTab.value = tab; void refreshActiveTab() }

async function refreshActiveTab() {
  message.value = null
  loadError.value = null
  if (!props.identity || activeTab.value === 'runtime') return
  try {
    if (activeTab.value === 'security') authSessions.value = await listAuthSessions()
    if (activeTab.value === 'workspace' && isOwner.value) {
      ;[members.value, auditEvents.value] = await Promise.all([listTenantMembers(), listTenantAuditEvents()])
    }
  } catch { loadError.value = '加载失败，请检查权限或稍后重试。' }
}
async function revokeSession(session: AuthSession) {
  busy.value = true
  try { await revokeAuthSession(session.session_id); message.value = '设备会话已撤销。'; await refreshActiveTab() } catch { loadError.value = '撤销设备会话失败。' } finally { busy.value = false }
}
async function revokeOthers() {
  busy.value = true
  try { await revokeOtherAuthSessions(); message.value = '其他设备已全部撤销。'; await refreshActiveTab() } catch { loadError.value = '撤销其他设备失败。' } finally { busy.value = false }
}
async function inviteMember() {
  const email = memberEmail.value.trim()
  if (!email) return
  busy.value = true
  try { await addTenantMember(email, memberRole.value); memberEmail.value = ''; message.value = '成员已加入当前工作区。'; await refreshActiveTab() } catch { loadError.value = '添加成员失败。' } finally { busy.value = false }
}
async function changeRole(member: TenantMember, event: Event) {
  busy.value = true
  try { await updateTenantMemberRole(member.user_id, (event.target as HTMLSelectElement).value as TenantMember['role']); await refreshActiveTab() } catch { loadError.value = '更新成员角色失败。' } finally { busy.value = false }
}
async function removeMember(member: TenantMember) {
  busy.value = true
  try { await removeTenantMember(member.user_id); await refreshActiveTab() } catch { loadError.value = '移除成员失败。' } finally { busy.value = false }
}
watch(() => props.open, (open) => { if (open) void refreshActiveTab() })
watch(() => props.identity?.tenant.tenant_id, () => { authSessions.value = []; members.value = []; auditEvents.value = []; if (props.open) void refreshActiveTab() })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="console-layer" @click.self="emit('close')">
      <section class="runtime-console" aria-label="运行与工作区控制台">
        <header class="console-header">
          <div><p class="eyebrow">GEN TRIP / OBSERVABILITY</p><strong>{{ identity?.tenant.name || '本地规划环境' }}</strong></div>
          <button class="icon-button" type="button" aria-label="关闭控制台" @click="emit('close')">×</button>
        </header>
        <nav class="console-tabs" aria-label="控制台分区">
          <button :class="{ active: activeTab === 'runtime' }" type="button" @click="selectTab('runtime')">运行轨迹</button>
          <button :class="{ active: activeTab === 'security' }" type="button" :disabled="!identity" @click="selectTab('security')">设备会话</button>
          <button :class="{ active: activeTab === 'workspace' }" type="button" :disabled="!identity" @click="selectTab('workspace')">工作区</button>
        </nav>
        <p v-if="loadError" class="notice error">{{ loadError }}</p><p v-if="message" class="notice">{{ message }}</p>

        <div v-if="activeTab === 'runtime'" class="console-content">
          <div class="run-overview">
            <div class="overview-line"><span>LIVE RUN</span><b :class="{ online: llmEnabled }">{{ llmEnabled ? 'LLM ONLINE' : 'RULE FALLBACK' }}</b></div>
            <code>{{ activeRunId || route?.run_id || '暂无运行任务' }}</code>
            <small>{{ loading ? `正在执行 · ${currentPhase}` : (route?.run_status || 'idle') }}{{ llmModel ? ` · ${llmModel}` : '' }}</small>
          </div>
          <div class="metric-grid"><div><span>LLM 调用</span><strong>{{ liveUsage?.call_count ?? 0 }}</strong></div><div><span>总 tokens</span><strong>{{ liveUsage?.total_tokens ?? 0 }}</strong></div><div><span>实时节点</span><strong>{{ liveEvents.length }}</strong></div></div>

          <section class="console-section">
            <div class="section-heading"><h3>执行轨迹</h3><span>{{ latestEvent?.phase || '等待任务' }}</span></div>
            <ol v-if="liveEvents.length" class="phase-list">
              <li v-for="(event, index) in liveEvents" :key="`${event.event_id || event.phase}-${index}`" :class="{ current: loading && index === liveEvents.length - 1 }">
                <span class="phase-status" :class="event.status || 'running'" /><div class="phase-copy"><div class="phase-title"><strong>{{ event.phase }}</strong><small>{{ event.status || 'running' }}</small></div><p>{{ event.summary || '节点已收到执行机会' }}</p><div v-if="details(event).length" class="event-details"><span v-for="([key, value]) in details(event)" :key="key"><b>{{ key }}</b>{{ displayValue(value) }}</span></div></div>
              </li>
            </ol><p v-else class="empty-state">提交任务后，这里会实时显示每个节点的输出。</p>
          </section>

          <section class="console-section"><div class="section-heading"><h3>LLM 调用</h3><span>{{ liveLlmCalls.length }} calls</span></div>
            <div v-if="liveLlmCalls.length" class="call-list"><article v-for="(call, index) in liveLlmCalls" :key="`${call.operation}-${index}`"><div><strong>{{ call.operation }}</strong><span :class="String(call.status)">{{ call.status }}</span></div><small>{{ call.provider }} / {{ call.model || 'default' }} · {{ call.total_tokens || 0 }} tokens · {{ call.latency_ms || 0 }} ms</small></article></div><p v-else class="empty-state">本轮尚未产生 LLM 调用。</p>
          </section>
          <section class="console-section"><div class="section-heading"><h3>工具与降级</h3><span>{{ liveToolCalls.length }} calls</span></div>
            <div v-if="liveToolCalls.length" class="tool-list"><article v-for="(call, index) in liveToolCalls" :key="`${toolName(call)}-${index}`"><strong>{{ toolName(call) }}</strong><small>{{ toolStatus(call) }}</small></article></div><p v-else class="empty-state">本轮尚未产生额外工具调用。</p>
            <p v-if="route?.meta.data_sources?.length" class="tool-summary">数据来源：{{ route.meta.data_sources.join('、') }}</p><p v-if="route?.meta.degraded_reasons?.length" class="degraded-summary">降级原因：{{ route.meta.degraded_reasons.join('，') }}</p>
          </section>
        </div>

        <div v-else-if="activeTab === 'security'" class="console-content"><div class="section-heading"><h3>已登录设备</h3><button class="text-button" type="button" :disabled="busy" @click="revokeOthers">撤销其他设备</button></div><article v-for="item in authSessions" :key="item.session_id" class="row"><div><strong>{{ item.current ? '当前设备' : item.tenant_id }}</strong><small>{{ formatDate(item.created_at) }} 登录</small></div><button v-if="!item.current" class="text-button" type="button" :disabled="busy" @click="revokeSession(item)">撤销</button></article><p v-if="!authSessions.length" class="empty-state">暂无可显示的设备会话。</p></div>

        <div v-else class="console-content"><template v-if="isOwner"><div class="section-heading"><h3>成员</h3><span>{{ members.length }}</span></div><form class="member-form" @submit.prevent="inviteMember"><input v-model="memberEmail" type="email" autocomplete="email" placeholder="成员邮箱"><select v-model="memberRole"><option value="member">成员</option><option value="owner">所有者</option></select><button type="submit" :disabled="busy || !memberEmail.trim()">添加</button></form><article v-for="member in members" :key="member.user_id" class="row"><div><strong>{{ member.display_name || member.email }}</strong><small>{{ member.email }}</small></div><select :value="member.role" :disabled="busy" @change="changeRole(member, $event)"><option value="member">成员</option><option value="owner">所有者</option></select><button class="text-button" type="button" :disabled="busy || member.user_id === identity?.user.user_id" @click="removeMember(member)">移除</button></article><section class="console-section"><h3>近期审计</h3><article v-for="event in auditEvents" :key="event.event_id" class="audit-row"><strong>{{ event.action }}</strong><small>{{ event.target_type }} · {{ formatDate(event.created_at) }}</small></article></section></template><p v-else class="empty-state">当前账号没有管理工作区的权限。</p></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.console-layer{position:fixed;z-index:50;inset:0;display:flex;justify-content:flex-end;background:rgba(15,39,28,.3);backdrop-filter:blur(3px)}
.runtime-console{width:min(560px,100vw);height:100%;overflow:auto;background:#fbfdfb;color:#18362a;border-left:1px solid #c8ddd0;box-shadow:-20px 0 50px rgba(16,54,35,.2)}
.console-header{display:flex;align-items:center;justify-content:space-between;padding:24px 26px 19px;border-bottom:1px solid #dbe9df}.eyebrow{margin:0 0 7px;color:#2c956c;font:700 10px/1.2 ui-monospace,SFMono-Regular,monospace;letter-spacing:.14em}.console-header strong{font:600 22px Georgia,"Noto Serif SC",serif}.icon-button{width:30px;height:30px;border:1px solid #c5dbcc;border-radius:50%;background:#fff;color:#286b4c;font-size:21px;line-height:1;cursor:pointer}
.console-tabs{display:grid;grid-template-columns:repeat(3,1fr);padding:0 26px;border-bottom:1px solid #dbe9df}.console-tabs button{padding:13px 6px 11px;border:0;border-bottom:2px solid transparent;background:none;color:#789087;font-size:12px;cursor:pointer}.console-tabs button.active{border-color:#17865d;color:#17865d;font-weight:700}.console-tabs button:disabled{color:#b8c8be;cursor:not-allowed}.console-content{padding:22px 26px 38px}.notice{margin:14px 26px 0;padding:10px;border-radius:6px;background:#eaf7ef;color:#317456;font-size:12px}.notice.error{background:#fff0ee;color:#a94e47}
.run-overview{display:grid;gap:8px;padding:15px;border:1px solid #cfe5d6;background:#f3faf5;border-radius:9px}.overview-line{display:flex;justify-content:space-between;color:#277452;font:700 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em}.overview-line b{color:#9b7627}.overview-line b.online{color:#1c9562}.run-overview code{overflow:hidden;color:#1e6648;font:12px ui-monospace,SFMono-Regular,monospace;text-overflow:ellipsis;white-space:nowrap}.run-overview small{color:#789087;font-size:11px}.metric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.metric-grid div{padding:11px;border:1px solid #e0ece3;border-radius:7px;background:#fff}.metric-grid span,.metric-grid strong{display:block}.metric-grid span{color:#789087;font-size:11px}.metric-grid strong{margin-top:5px;color:#1d563d;font-size:19px}
.console-section{margin-top:26px}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}.section-heading h3{margin:0;font-size:14px}.section-heading>span{color:#80948a;font:10px ui-monospace,SFMono-Regular,monospace}.phase-list{position:relative;display:grid;gap:0;margin:14px 0 0;padding:0;list-style:none}.phase-list:before{position:absolute;top:8px;bottom:8px;left:4px;width:1px;background:#d7e8dc;content:""}.phase-list li{position:relative;display:flex;gap:12px;padding:0 0 17px}.phase-list li.current .phase-copy{border-color:#9ed9b7;background:#f1faf3}.phase-status{z-index:1;width:9px;height:9px;flex:0 0 auto;margin-top:4px;border:2px solid #fbfdfb;border-radius:50%;background:#a9bcb0;box-shadow:0 0 0 1px #b9d5c2}.phase-status.completed,.phase-status.success{background:#269565}.phase-status.failed{background:#d05b53}.phase-status.running{background:#d19c32}.phase-copy{min-width:0;flex:1;padding:8px 10px;border:1px solid #e4eee7;border-radius:7px;background:#fff}.phase-title{display:flex;justify-content:space-between;gap:10px}.phase-title strong{font:700 12px ui-monospace,SFMono-Regular,monospace;color:#225e43}.phase-title small{color:#7f9589;font-size:10px}.phase-copy p{margin:5px 0 0;color:#5f776a;font-size:12px;line-height:1.5}.event-details{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.event-details span{max-width:100%;padding:3px 6px;border-radius:4px;background:#f0f6f1;color:#587568;font:10px ui-monospace,SFMono-Regular,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-details b{margin-right:4px;color:#2b805b}.call-list,.tool-list{display:grid;gap:8px;margin-top:12px}.call-list article,.tool-list article{padding:10px 11px;border:1px solid #e0ece3;border-radius:7px;background:#fff}.call-list div{display:flex;justify-content:space-between;gap:10px}.call-list span{font:10px ui-monospace,SFMono-Regular,monospace}.call-list .success{color:#25865b}.call-list .failed{color:#b34d45}.call-list .fallback,.call-list .skipped{color:#a07a26}.call-list small,.tool-list small,.row small,.audit-row small{display:block;margin-top:5px;color:#7a9084;font-size:11px}.tool-list article{display:flex;justify-content:space-between;gap:10px}.tool-list strong{font-size:12px}.empty-state,.tool-summary,.degraded-summary{margin:11px 0 0;color:#7b9185;font-size:12px;line-height:1.6}.degraded-summary{color:#9b7522}.text-button,.member-form button{border:1px solid #bfdcc9;border-radius:5px;background:#fff;color:#28704f;padding:6px 9px;font-size:11px;cursor:pointer}.row{display:flex;align-items:center;gap:10px;padding:13px 0;border-bottom:1px solid #e4eee7}.row>div{min-width:0;flex:1}.row strong{display:block;overflow:hidden;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.member-form{display:grid;grid-template-columns:minmax(0,1fr) 84px 54px;gap:7px;margin:13px 0 4px}.member-form input,.member-form select,.row select{min-width:0;padding:7px;border:1px solid #cfe2d5;border-radius:5px;background:#fff;color:#28523e;font-size:11px}.member-form button{padding:7px}.audit-row{padding:10px 0;border-bottom:1px solid #e4eee7}.audit-row strong{font-size:12px}
button:disabled{opacity:.5;cursor:not-allowed}@media(max-width:560px){.console-header,.console-content{padding-left:16px;padding-right:16px}.console-tabs{padding:0 16px}.notice{margin-left:16px;margin-right:16px}.member-form{grid-template-columns:minmax(0,1fr) 76px}.member-form button{grid-column:1/-1}}
</style>
