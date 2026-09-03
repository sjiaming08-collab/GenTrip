<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import RoutePlanner from './components/RoutePlanner.vue'
import AuthGate from './components/AuthGate.vue'
import RuntimeConsole from './components/RuntimeConsole.vue'
import RouteTurnCard from './components/RouteTurnCard.vue'
import RuntimeProgress from './components/RuntimeProgress.vue'
import { deleteSession, getCurrentUser, getHealth, getSession, listSessions, listWorkspaces, logout as logoutRequest, submitFeedback as saveFeedback, switchWorkspace, updateSessionTitle, type AuthIdentity, type Workspace } from './api'
import { useRoutePlan } from './composables/useRoutePlan'
import type { FeedbackRequest, RoutePlanRequest, RouteStop, RouteTurnSnapshot, SessionDetail } from './types'
import { snapshotFromResponse, snapshotFromTurn } from './utils/routeSnapshots'

type HistorySession = {
  sessionId: string
  title: string
  summary: string
  updatedAt: string
  routeCount: number
}

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  time: string
  routeSnapshot?: RouteTurnSnapshot
}

const SETTINGS_STORAGE_KEY = 'gentrip-agent-settings'

const {
  loading,
  currentPhase,
  currentRoute,
  routeResults,
  presentation,
  error,
  activeRunId,
  runtimeEvents,
  submitQuery,
  cancelPlanning,
  resetPlanningState,
  restoreRoute,
  recoverActiveRun,
} = useRoutePlan()

const selectedStop = ref<RouteStop | null>(null)
const sessionId = ref<string | null>(null)
const historySessions = ref<HistorySession[]>([])
const messages = ref<ChatMessage[]>([])
const expandedSnapshotIds = ref<Set<string>>(new Set())
const conversationThread = ref<HTMLElement | null>(null)
const editingTitle = ref(false)
const titleDraft = ref('')
const defaultDistrict = ref('跟随当前位置')
const defaultBudget = ref(150)
const defaultDuration = ref(180)
const profileId = ref('local-traveler')
const useDefaults = ref(true)
const authRequired = ref(false)
const authUser = ref<AuthIdentity | null>(null)
const workspaces = ref<Workspace[]>([])
const consoleOpen = ref(false)
const preferencesOpen = ref(false)
const llmEnabled = ref(false)
const llmModel = ref<string | null>(null)
const locating = ref(false)

const activeSession = computed(() => historySessions.value.find((item) => item.sessionId === sessionId.value))
const activeTitle = computed(() => activeSession.value?.title || '新路线对话')
const latestRouteSnapshotId = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const snapshot = messages.value[index].routeSnapshot
    if (snapshot) return snapshot.snapshot_id
  }
  return null
})

function nowTime() {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function buildRequest(request: RoutePlanRequest): RoutePlanRequest {
  const query = request.query.trim()
  const identityFields = { tenant_id: authUser.value?.tenant.tenant_id, user_id: profileId.value || undefined }
  if (!useDefaults.value) return { ...request, ...identityFields, query }

  const additions: string[] = []
  if (!/\d+\s*(元|块)/.test(query)) additions.push(`人均${defaultBudget.value}元`)
  if (!/\d+\s*(小时|h|分钟)/i.test(query) && !/半天/.test(query)) additions.push(`${defaultDuration.value / 60}小时`)

  return {
    ...request,
    ...identityFields,
    query: additions.length ? `${query}，${additions.join('，')}` : query,
  }
}

function currentCoordinates(): Promise<Pick<RoutePlanRequest, 'lat' | 'lng'>> {
  if (!navigator.geolocation) return Promise.resolve({})
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ lat: coords.latitude, lng: coords.longitude }),
      () => resolve({}),
      { enableHighAccuracy: false, timeout: 2500, maximumAge: 300000 },
    )
  })
}

function addMessage(role: ChatMessage['role'], text: string, routeSnapshot?: RouteTurnSnapshot) {
  if (routeSnapshot) {
    const existingIndex = messages.value.findIndex((item) => item.routeSnapshot?.snapshot_id === routeSnapshot.snapshot_id)
    if (existingIndex >= 0) {
      messages.value[existingIndex] = { ...messages.value[existingIndex], text, routeSnapshot }
      return
    }
  }
  messages.value.push({ id: crypto.randomUUID(), role, text, time: nowTime(), routeSnapshot })
}

function expandOnlySnapshot(snapshotId: string | null) {
  expandedSnapshotIds.value = new Set(snapshotId ? [snapshotId] : [])
}

function toggleSnapshot(snapshotId: string) {
  const next = new Set(expandedSnapshotIds.value)
  if (next.has(snapshotId)) next.delete(snapshotId)
  else next.add(snapshotId)
  expandedSnapshotIds.value = next
}

function scrollToLatestMessage(behavior: ScrollBehavior = 'smooth') {
  void nextTick(() => {
    conversationThread.value?.scrollTo({
      top: conversationThread.value.scrollHeight,
      behavior,
    })
  })
}

async function refreshHistory() {
  const sessions = await listSessions(profileId.value || 'local-traveler')
  historySessions.value = sessions.map((item) => ({
    sessionId: item.session_id,
    title: item.title || '未命名路线',
    summary: item.dialog_summary || '已保存会话',
    updatedAt: item.updated_at ? new Date(item.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '',
    routeCount: item.route_count,
  }))
}

function applyIdentity(identity: AuthIdentity) {
  authUser.value = identity
  profileId.value = identity.user.user_id
  void refreshHistory()
  void refreshWorkspaces()
}

async function refreshWorkspaces() {
  if (!authUser.value) return
  try { workspaces.value = await listWorkspaces() } catch { workspaces.value = [] }
}

async function changeWorkspace(event: Event) {
  const tenantId = (event.target as HTMLSelectElement).value
  if (!tenantId || tenantId === authUser.value?.tenant.tenant_id) return
  try {
    const identity = await switchWorkspace(tenantId)
    authUser.value = identity
    sessionId.value = null
    historySessions.value = []
    messages.value = []
    resetPlanningState()
    await refreshHistory()
  } catch {
    error.value = '无法切换工作区，请稍后重试。'
  }
}

async function signOut() {
  await logoutRequest()
  authUser.value = null
  workspaces.value = []
  sessionId.value = null
  historySessions.value = []
  messages.value = []
  resetPlanningState()
}

function saveHistory(query: string) {
  if (!currentRoute.value?.session_id) return
  const existing = historySessions.value.find((entry) => entry.sessionId === currentRoute.value?.session_id)
  const item: HistorySession = {
    sessionId: currentRoute.value.session_id,
    title: existing?.title || query,
    summary: presentation.value?.summary || routeResults.value[0]?.route.summary || '已生成路线',
    updatedAt: nowTime(),
    routeCount: routeResults.value.length,
  }
  historySessions.value = [item, ...historySessions.value.filter((entry) => entry.sessionId !== item.sessionId)].slice(0, 12)
}

async function handleSubmit(request: RoutePlanRequest) {
  const previousLatestSnapshotId = latestRouteSnapshotId.value
  expandOnlySnapshot(null)
  selectedStop.value = null
  let enriched = buildRequest({ ...request, session_id: request.session_id || sessionId.value || undefined })
  if (enriched.lat == null || enriched.lng == null) {
    locating.value = true
    try {
      enriched = { ...enriched, ...(await currentCoordinates()) }
    } finally {
      locating.value = false
    }
  }
  addMessage('user', request.query.trim())
  await submitQuery(enriched)

  if (error.value === 'authentication_required' && authRequired.value) {
    authUser.value = null
    workspaces.value = []
    sessionId.value = null
    historySessions.value = []
    messages.value = []
    return
  }

  if (error.value || !currentRoute.value) {
    expandOnlySnapshot(previousLatestSnapshotId)
    return
  }

  if (currentRoute.value?.session_id) {
    sessionId.value = currentRoute.value.session_id
    addMessage(
      'assistant',
      presentation.value?.summary || '路线已生成，已在下方展示。',
      snapshotFromResponse(currentRoute.value, request.query.trim()),
    )
    expandOnlySnapshot(currentRoute.value.turn_id || currentRoute.value.run_id)
    saveHistory(request.query.trim())
    try {
      await refreshHistory()
    } catch {
      // The completed route remains usable even when the history refresh fails.
    }
  }
}

function startNewSession() {
  sessionId.value = null
  selectedStop.value = null
  messages.value = []
  expandOnlySnapshot(null)
  editingTitle.value = false
  resetPlanningState()
  void nextTick(() => conversationThread.value?.scrollTo({ top: 0 }))
}

async function selectHistory(item: HistorySession) {
  try {
    const detail: SessionDetail = await getSession(item.sessionId)
    sessionId.value = item.sessionId
    selectedStop.value = null
    resetPlanningState()
    messages.value = detail.turns.flatMap((turn) => {
      const result: ChatMessage[] = [{
        id: `user-${turn.turn_id}`,
        role: 'user',
        text: turn.user_query,
        time: new Date(turn.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      }]
      const assistantText = turn.assistant_message || turn.presentation?.summary
      if (assistantText || turn.route_results.length) {
        result.push({
          id: `assistant-${turn.turn_id}`,
          role: 'assistant',
          text: assistantText || '该轮路线已生成。',
          time: new Date(turn.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          routeSnapshot: snapshotFromTurn(turn, item.sessionId),
        })
      }
      return result
    })
    const lastSnapshot = [...messages.value].reverse().find((message) => message.routeSnapshot)?.routeSnapshot
    expandOnlySnapshot(lastSnapshot?.snapshot_id ?? null)
    if (detail.latest_response) restoreRoute(detail.latest_response)
    editingTitle.value = false
    scrollToLatestMessage('auto')
  } catch {
    error.value = '无法加载该历史会话，请稍后重试。'
  }
}

function beginTitleEdit() {
  if (!activeSession.value) return
  titleDraft.value = activeSession.value.title
  editingTitle.value = true
}

async function saveTitle() {
  const title = titleDraft.value.trim()
  if (title && sessionId.value) {
    const saved = await updateSessionTitle(sessionId.value, title)
    historySessions.value = historySessions.value.map((item) => (
      item.sessionId === saved.session_id ? { ...item, title: saved.title } : item
    ))
  }
  editingTitle.value = false
}

async function removeActiveSession() {
  if (!sessionId.value || loading.value) return
  if (!window.confirm('删除此会话及其路线记录？此操作无法撤销。')) return
  const deletedId = sessionId.value
  try {
    await deleteSession(deletedId)
    historySessions.value = historySessions.value.filter((item) => item.sessionId !== deletedId)
    startNewSession()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '删除会话失败，请稍后重试。'
  }
}

function handleSelectStop(stop: RouteStop) {
  selectedStop.value = stop
}

async function handleFeedback(feedback: FeedbackRequest) {
  await saveFeedback({
    ...feedback,
    session_id: feedback.session_id || currentRoute.value?.session_id || sessionId.value || '',
    tenant_id: authUser.value?.tenant.tenant_id,
  })
}

function handleSuggestion(query: string) {
  void handleSubmit({ query, session_id: sessionId.value ?? undefined })
}

onMounted(async () => {
  try {
    const savedSettings = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) || '{}')
    defaultDistrict.value = '跟随当前位置'
    defaultBudget.value = savedSettings.defaultBudget || defaultBudget.value
    defaultDuration.value = savedSettings.defaultDuration || defaultDuration.value
    profileId.value = savedSettings.profileId || profileId.value
    useDefaults.value = savedSettings.useDefaults ?? useDefaults.value
  } catch { /* Use the built-in defaults when browser preferences are unavailable. */ }
  try {
    const health = await getHealth()
    authRequired.value = health.auth_enabled
    llmEnabled.value = Boolean(health.llm_enabled)
    llmModel.value = health.llm_model || null
    try { applyIdentity(await getCurrentUser()) } catch { /* Anonymous local mode remains available when disabled. */ }
    if (!authRequired.value || authUser.value) await refreshHistory()
    const restored = await recoverActiveRun()
    if (restored) {
      sessionId.value = restored.session_id ?? null
      addMessage(
        'assistant',
        restored.presentation?.summary || '已恢复此前完成的路线规划。',
        snapshotFromResponse(restored),
      )
      expandOnlySnapshot(restored.turn_id || restored.run_id)
      await refreshHistory()
    }
  } catch { historySessions.value = [] }
})

watch([defaultDistrict, defaultBudget, defaultDuration, profileId, useDefaults], () => {
  localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
    defaultDistrict: defaultDistrict.value,
    defaultBudget: defaultBudget.value,
    defaultDuration: defaultDuration.value,
    profileId: profileId.value,
    useDefaults: useDefaults.value,
  }))
  if (!authRequired.value || authUser.value) void refreshHistory()
})

watch(
  [() => messages.value.length, loading, currentRoute],
  () => scrollToLatestMessage(),
  { flush: 'post' },
)
</script>

<template>
  <AuthGate v-if="authRequired && !authUser" @authenticated="applyIdentity" />
  <div v-else class="agent-shell">
    <aside class="history-rail">
      <div class="brand-lockup">
        <div class="brand-mark">G</div>
        <div>
          <strong>GenTrip</strong>
          <span>城市路线 Agent</span>
        </div>
      </div>

      <button class="new-session" type="button" @click="startNewSession">新建路线对话</button>
      <button
        v-if="activeSession"
        class="rail-session-delete"
        type="button"
        :disabled="loading"
        @click="removeActiveSession"
      >删除当前会话</button>

      <div class="rail-heading">
        <span>最近会话</span>
        <span class="count">{{ historySessions.length }}</span>
      </div>
      <nav class="session-list" aria-label="历史会话">
        <button
          v-for="item in historySessions"
          :key="item.sessionId"
          class="session-item"
          :class="{ selected: item.sessionId === sessionId }"
          type="button"
          @click="selectHistory(item)"
        >
          <strong>{{ item.title }}</strong>
          <span>{{ item.summary }}</span>
          <small>{{ item.updatedAt }} · {{ item.routeCount }} 条方案</small>
        </button>
        <p v-if="!historySessions.length" class="empty-history">规划过的路线会保存在这里</p>
      </nav>

      <div class="rail-footer">
        <span class="presence-dot" />
        <span>{{ authUser ? authUser.user.display_name : '路线引擎在线' }}</span>
        <button v-if="authUser" class="logout-button" type="button" @click="signOut">退出</button>
      </div>
      <label v-if="authUser && workspaces.length > 1" class="workspace-switch">
        <span>旅行空间</span>
        <select :value="authUser.tenant.tenant_id" @change="changeWorkspace">
          <option v-for="workspace in workspaces" :key="workspace.tenant_id" :value="workspace.tenant_id">
            {{ workspace.name }}
          </option>
        </select>
      </label>
    </aside>

    <main class="conversation-workspace">
      <header class="workspace-header">
        <div>
          <p class="eyebrow">当前对话</p>
          <div class="title-row">
            <input
              v-if="editingTitle"
              v-model="titleDraft"
              class="title-input"
              aria-label="会话标题"
              autofocus
              @blur="saveTitle"
              @keydown.enter.prevent="saveTitle"
              @keydown.esc="editingTitle = false"
            >
            <template v-else>
              <h1>{{ activeTitle }}</h1>
              <button v-if="activeSession" class="title-edit" type="button" @click="beginTitleEdit">编辑</button>
            </template>
          </div>
        </div>
        <div class="header-actions">
          <div class="session-state">
            <span class="state-dot" />
            {{ loading ? '规划中' : '可继续调整' }}
          </div>
          <button class="console-trigger" type="button" @click="consoleOpen = true">运行详情</button>
        </div>
      </header>

      <section ref="conversationThread" class="conversation-thread" aria-live="polite">
        <article v-if="!messages.length" class="message assistant-message welcome-message">
          <span class="avatar">G</span>
          <div>
            <p class="message-name">GenTrip</p>
            <p>告诉我你想去哪里、和谁出行，或直接说“附近有什么好玩的”。我会先给出一条可执行的路线。</p>
          </div>
        </article>

        <template v-for="message in messages" :key="message.id">
          <article class="message" :class="`${message.role}-message`">
            <span v-if="message.role === 'assistant'" class="avatar">G</span>
            <div class="message-bubble">
              <p class="message-name">{{ message.role === 'assistant' ? 'GenTrip' : '你' }} · {{ message.time }}</p>
              <p>{{ message.text }}</p>
            </div>
          </article>
          <RouteTurnCard
            v-if="message.routeSnapshot"
            :snapshot="message.routeSnapshot"
            :is-latest="message.routeSnapshot.snapshot_id === latestRouteSnapshotId"
            :expanded="expandedSnapshotIds.has(message.routeSnapshot.snapshot_id)"
            :selected-stop-id="selectedStop?.poi_id ?? null"
            @select-stop="handleSelectStop"
            @submit-feedback="handleFeedback"
            @suggestion="handleSuggestion"
            @toggle="toggleSnapshot(message.routeSnapshot.snapshot_id)"
          />
        </template>

        <article v-if="loading" class="assistant-progress">
          <div class="progress-copy">
            <span class="avatar">G</span>
            <div><strong>正在规划路线</strong><span>{{ currentPhase }}</span></div>
          </div>
          <RuntimeProgress :events="runtimeEvents" :loading="loading" :current-phase="currentPhase" @cancel="cancelPlanning" />
        </article>

        <p v-if="error" class="error-state">{{ error }}</p>

      </section>

      <div class="composer-dock">
        <div class="planning-context" :class="{ inactive: !useDefaults }">
          <span>默认约束</span>
          <button type="button" @click="preferencesOpen = true">{{ defaultDistrict }}</button>
          <button type="button" @click="preferencesOpen = true">人均 {{ defaultBudget }} 元</button>
          <button type="button" @click="preferencesOpen = true">{{ defaultDuration / 60 }} 小时</button>
          <button class="context-toggle" type="button" @click="useDefaults = !useDefaults">{{ useDefaults ? '已启用' : '未启用' }}</button>
          <button class="context-settings" type="button" @click="preferencesOpen = true">调整</button>
        </div>
        <RoutePlanner :is-loading="loading || locating" @submit="handleSubmit" />
      </div>
    </main>

    <aside class="settings-rail" :class="{ open: preferencesOpen }">
      <button class="close-preferences" type="button" @click="preferencesOpen = false">关闭</button>
      <div class="settings-header">
        <p class="eyebrow">规划偏好</p>
        <h2>这次怎么安排</h2>
      </div>

      <label class="setting-switch">
        <span><strong>自动补全偏好</strong><small>只在用户未明确说明时应用</small></span>
        <input v-model="useDefaults" type="checkbox">
      </label>

      <div class="settings-form" :class="{ muted: !useDefaults }">
        <label>
          位置范围
          <select v-model="defaultDistrict" :disabled="!useDefaults">
            <option>跟随当前位置</option>
          </select>
        </label>
        <label>
          人均预算
          <select v-model.number="defaultBudget" :disabled="!useDefaults">
            <option :value="100">100 元</option><option :value="150">150 元</option><option :value="200">200 元</option><option :value="300">300 元</option>
          </select>
        </label>
        <label>
          默认时长
          <select v-model.number="defaultDuration" :disabled="!useDefaults">
            <option :value="120">2 小时</option><option :value="180">3 小时</option><option :value="240">4 小时 / 半天</option>
          </select>
        </label>
      </div>

      <div class="settings-divider" />
      <label class="profile-setting">
        <span>偏好档案</span>
        <input v-model="profileId" placeholder="匿名用户">
      </label>

      <div class="session-card">
        <span>当前会话</span>
        <strong>{{ sessionId ? sessionId.slice(0, 8) : '尚未开始' }}</strong>
        <small>{{ currentRoute?.meta?.token_usage?.total_tokens ? `本轮 ${currentRoute.meta.token_usage.total_tokens} tokens` : '模型用量将在完成后显示' }}</small>
      </div>
      <button class="console-rail-button" type="button" @click="consoleOpen = true">查看运行明细</button>
    </aside>
    <RuntimeConsole :open="consoleOpen" :identity="authUser" :route="currentRoute" :active-run-id="activeRunId" :events="runtimeEvents" :loading="loading" :current-phase="currentPhase" :llm-enabled="llmEnabled" :llm-model="llmModel" @close="consoleOpen = false" />
  </div>
</template>

<style scoped>
:global(*) { box-sizing: border-box; letter-spacing: 0 !important; }
:global(html), :global(body), :global(#app) { height: 100%; }
:global(body) { margin: 0; min-width: 320px; overflow: hidden; background: #f3f5f4; color: #25332d; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; }
:global(button), :global(input), :global(select), :global(textarea) { font: inherit; }

.agent-shell { height: 100dvh; min-height: 0; display: grid; grid-template-columns: 272px minmax(0, 1fr) 292px; overflow: hidden; background: #f3f5f4; }
.history-rail, .settings-rail { min-height: 0; height: 100%; overflow-y: auto; background: #ffffff; border-color: #dcebe1; }
.history-rail { display: flex; flex-direction: column; padding: 24px 16px 18px; border-right: 1px solid #dcebe1; }
.settings-rail { padding: 28px 22px; border-left: 1px solid #dcebe1; }
.brand-lockup { display: flex; gap: 10px; align-items: center; padding: 0 6px 24px; }
.brand-mark, .avatar { display: inline-flex; align-items: center; justify-content: center; background: #167b59; color: #fff; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; font-weight: 700; }
.brand-mark { width: 32px; height: 32px; border-radius: 10px; font-size: 18px; }
.brand-lockup strong { display: block; font-size: 17px; letter-spacing: .02em; }
.brand-lockup span { display: block; margin-top: 2px; color: #749184; font-size: 12px; }
.new-session { width: 100%; padding: 10px 12px; border: 1px solid #167b59; border-radius: 10px; background: #167b59; color: #fff; cursor: pointer; font-weight: 700; }
.new-session:hover { background: #0e6748; }
.rail-session-delete { width: 100%; margin-top: 7px; padding: 8px 10px; border: 1px solid #ead6d1; border-radius: 10px; background: #fffafa; color: #9c4a43; cursor: pointer; font-size: 12px; text-align: left; }.rail-session-delete:hover { border-color: #cc8b83; background: #fff3f1; color: #82352f; }.rail-session-delete:disabled { cursor: not-allowed; opacity: .45; }
.rail-heading { display: flex; justify-content: space-between; align-items: center; margin: 28px 6px 10px; color: #608071; font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.count { display: inline-flex; min-width: 20px; justify-content: center; padding: 2px 6px; border-radius: 999px; background: #e8f4ec; color: #177657; }
.session-list { display: grid; gap: 5px; overflow-y: auto; }
.session-item { width: 100%; display: grid; gap: 5px; padding: 11px 10px; text-align: left; border: 1px solid transparent; border-radius: 10px; background: transparent; color: #2f3e37; cursor: pointer; }
.session-item:hover, .session-item.selected { background: #f1f7f3; border-color: #d2e4d8; }
.session-item strong, .session-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item strong { font-size: 13px; }
.session-item span { color: #6e8b7d; font-size: 12px; }
.session-item small { color: #94aa9f; font-size: 11px; }
.empty-history { margin: 16px 8px; color: #91a79b; font-size: 12px; line-height: 1.6; }
.rail-footer { display: flex; gap: 8px; align-items: center; margin-top: auto; padding: 14px 7px 0; color: #688477; font-size: 12px; }
.logout-button { margin-left: auto; padding: 2px 0; border: 0; background: transparent; color: #5c8471; cursor: pointer; font-size: 12px; }.logout-button:hover { color: #135e42; text-decoration: underline; }
.workspace-switch { display: grid; gap: 5px; margin: 11px 7px 0; color: #718c7e; font-size: 11px; }.workspace-switch select { width: 100%; padding: 6px 7px; border: 1px solid #cfe4d6; border-radius: 6px; background: #fbfefc; color: #28523e; font-size: 12px; }
.presence-dot, .state-dot { width: 8px; height: 8px; border-radius: 50%; background: #38a879; box-shadow: 0 0 0 3px #e6f5eb; }

.conversation-workspace { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 0 32px; }
.workspace-header { position: relative; z-index: 1; flex: 0 0 auto; min-height: 96px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #dcebe1; background: #f1f8f3; }
.eyebrow { margin: 0 0 6px; color: #4a9171; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.workspace-header h1, .settings-header h2, .reply-summary h2 { margin: 0; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; font-weight: 700; }
.workspace-header h1 { font-size: 23px; }
.title-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
.title-edit { padding: 3px 0; border: 0; background: transparent; color: #398364; font-size: 12px; cursor: pointer; }
.title-edit:hover { color: #135e42; text-decoration: underline; }
.title-input { width: min(360px, 58vw); padding: 7px 10px; border: 1px solid #b9d7c4; border-radius: 10px; background: #fff; color: #25332d; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; font-size: 20px; font-weight: 700; outline: none; box-shadow: 0 0 0 3px rgba(39, 130, 91, .08); }
.header-actions { display: flex; align-items: center; gap: 10px; margin-left: auto; }.session-state { display: flex; align-items: center; gap: 9px; color: #5e7f70; font-size: 13px; }.console-trigger, .console-rail-button { border: 1px solid #bedfca; border-radius: 6px; background: #fff; color: #276a4c; cursor: pointer; font-size: 12px; }.console-trigger { padding: 7px 9px; }.console-trigger:hover, .console-rail-button:hover { border-color: #167b59; background: #edf8f0; }.console-rail-button { width: 100%; margin-top: 12px; padding: 8px 10px; text-align: left; }
.conversation-thread { width: min(100%, 850px); min-height: 0; flex: 1 1 auto; margin: 0 auto; overflow-y: auto; overscroll-behavior: contain; padding: 34px 0; scroll-behavior: smooth; }
.message { display: flex; gap: 11px; margin-bottom: 20px; }
.assistant-message { max-width: 82%; }
.user-message { justify-content: flex-end; }
.avatar { flex: 0 0 30px; height: 30px; border-radius: 50%; font-size: 14px; }
.message-bubble { max-width: 100%; padding: 12px 14px; border: 1px solid #d9e1dc; border-radius: 12px; background: #fff; color: #34423b; line-height: 1.65; box-shadow: 0 3px 12px rgba(37, 51, 45, .04); }
.user-message .message-bubble { max-width: 72%; border-color: #caddeb; background: #edf5fb; color: #2f4658; }
.message-bubble p { margin: 0; }
.message-name { margin-bottom: 4px !important; color: #729083; font-size: 11px; }
.welcome-message .message-bubble { padding: 15px 17px; }
.assistant-progress { margin: 18px 0; padding: 16px; border: 1px solid #d8e3dc; border-radius: 12px; background: #fbfcfb; }
.progress-copy { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.progress-copy strong, .progress-copy span { display: block; }
.progress-copy strong { font-size: 14px; }.progress-copy span { margin-top: 3px; color: #739184; font-size: 12px; }
.error-state { margin: 16px 0; padding: 11px 13px; border: 1px solid #edcbc5; border-radius: 10px; background: #fff7f5; color: #9c443d; font-size: 13px; }
.route-response { margin-top: 24px; }
.reply-summary { padding: 20px 0; border-top: 1px solid #dcebe1; border-bottom: 1px solid #dcebe1; }
.reply-summary h2 { font-size: 24px; }.reply-summary > p:not(.eyebrow) { margin: 9px 0 0; color: #537265; line-height: 1.65; }
.reply-summary ul { display: grid; gap: 7px; margin: 14px 0 0; padding: 0; list-style: none; color: #456556; font-size: 14px; }
.reply-summary li::before { content: '•'; margin-right: 8px; color: #2a9567; }
.assumption-strip { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; margin: 18px 0; color: #547366; font-size: 12px; }
.assumption-strip strong { margin-right: 4px; color: #2b5946; }.assumption-strip span { padding: 5px 8px; border-radius: 999px; background: #e9f6ed; }
.degraded-notice, .diff-strip { margin: 16px 0; padding: 10px 12px; border-radius: 10px; font-size: 13px; }
.degraded-notice { background: #fff8e8; color: #906b22; border: 1px solid #f0dc9f; }.diff-strip { background: #eef8f1; color: #317255; }
.suggestion-row, .route-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.suggestion-row button, .route-tabs button { border: 1px solid #cfded4; border-radius: 10px; padding: 7px 10px; background: #fff; color: #35624e; cursor: pointer; font-size: 13px; }
.suggestion-row button:hover, .route-tabs button.active { border-color: #16805a; background: #e9f7ed; color: #116b4a; }
.route-tabs button span { margin-left: 5px; color: #6d8f7e; font-size: 11px; }.result-layout { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(270px, .95fr); gap: 14px; margin-top: 20px; }
.composer-dock { position: relative; z-index: 1; flex: 0 0 auto; width: min(100%, 850px); margin: auto; padding: 14px 0 20px; background: #f1f8f3; }

.settings-header { margin-bottom: 22px; }.settings-header h2 { font-size: 19px; }.setting-switch { display: flex; justify-content: space-between; gap: 10px; padding: 13px 0; border-top: 1px solid #e0eee4; border-bottom: 1px solid #e0eee4; cursor: pointer; }.setting-switch strong, .setting-switch small { display: block; }.setting-switch strong { font-size: 13px; }.setting-switch small { margin-top: 4px; color: #829c90; font-size: 11px; line-height: 1.45; }.setting-switch input { width: 34px; accent-color: #167b59; }
.settings-form { display: grid; gap: 14px; padding-top: 18px; transition: opacity .2s; }.settings-form.muted { opacity: .45; }.settings-form label, .profile-setting { display: grid; gap: 7px; color: #567768; font-size: 12px; font-weight: 700; }.settings-form select, .profile-setting input { width: 100%; padding: 9px 10px; border: 1px solid #cfe4d6; border-radius: 6px; background: #fbfefc; color: #28523e; outline: none; }.settings-form select:focus, .profile-setting input:focus { border-color: #3b9b70; box-shadow: 0 0 0 3px #e6f5ea; }.settings-divider { height: 1px; margin: 24px 0 18px; background: #e0eee4; }.session-card { display: grid; gap: 7px; margin-top: 26px; padding: 13px; border: 1px solid #d9ebdf; border-radius: 7px; background: #f7fcf8; }.session-card span, .session-card small { color: #789387; font-size: 11px; }.session-card strong { font-family: "Microsoft YaHei", "微软雅黑", sans-serif; color: #29664b; font-size: 13px; }

@media (max-width: 1180px) { .agent-shell { grid-template-columns: 236px minmax(0, 1fr); }.settings-rail { display: none; }.conversation-workspace { padding: 0 24px; } }
@media (max-width: 760px) { :global(body) { overflow: hidden; }.agent-shell { height: 100dvh; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }.history-rail { min-height: 0; height: auto; max-height: 188px; flex: 0 0 auto; padding: 12px 14px 9px; overflow: hidden; border-right: 0; border-bottom: 1px solid #dcebe1; }.brand-lockup { padding: 0 0 9px; }.new-session { width: 100%; padding: 8px 10px; }.rail-heading { margin: 10px 6px 6px; }.session-list { grid-auto-flow: column; grid-auto-columns: minmax(176px, 66%); overflow-x: auto; padding-bottom: 2px; }.session-item { gap: 3px; padding: 7px 9px; }.session-item span { display: none; }.rail-footer { display: none; }.conversation-workspace { min-height: 0; height: auto; flex: 1 1 auto; padding: 0 16px; }.workspace-header { min-height: 68px; }.workspace-header h1 { font-size: 19px; }.conversation-thread { padding-top: 18px; }.assistant-message, .user-message .message-bubble { max-width: 88%; }.result-layout { grid-template-columns: 1fr; }.composer-dock { padding-bottom: 10px; } }
/* Planning workspace overrides. The results canvas carries the primary visual weight. */
.agent-shell { grid-template-columns: 240px minmax(0, 1fr); background: #f3f5f4; }
.history-rail { padding: 22px 14px 16px; background: #fcfdfb; }
.conversation-workspace { padding: 0 28px; }
.workspace-header { min-height: 82px; background: #f3f5f4; }
.conversation-thread { width: min(100%, 1040px); padding: 26px 0 34px; }
.composer-dock { width: min(100%, 1040px); padding: 8px 0 18px; background: #f3f5f4; }
.message { margin-bottom: 15px; }
.message-bubble { border-color: #d5e1d8; box-shadow: none; }
.assistant-progress { margin: 16px 0; padding: 0; border: 0; background: transparent; }
.assistant-progress .progress-copy { display: none; }
.assistant-progress :deep(.runtime-progress) { margin: 0; }
.route-response { margin-top: 22px; }
.reply-summary { padding: 0 0 18px; border-top: 0; }
.reply-summary h2 { font-size: 26px; }
.route-tabs { margin: 15px 0; }
.planning-context { display:flex;align-items:center;gap:6px;min-height:31px;padding:0 1px 7px;overflow-x:auto;color:#71897e;white-space:nowrap; }
.planning-context>span { margin-right:3px;color:#789087;font-size:11px;font-weight:700; }
.planning-context button { padding:5px 8px;border:1px solid #d5dfd8;border-radius:9px;background:#fff;color:#426959;font-size:11px;cursor:pointer; }
.planning-context .context-toggle { margin-left:auto;border-color:#b5d4c0;color:#247252; }
.planning-context .context-settings { color:#8a5c2b; }
.planning-context.inactive button:not(.context-toggle):not(.context-settings) { opacity:.45; }
.settings-rail { position:fixed;z-index:30;top:0;right:0;width:min(330px,100vw);height:100dvh;padding-top:56px;overflow-y:auto;border-left:1px solid #d5e3d9;border-radius:16px 0 0 16px;box-shadow:-18px 0 42px rgba(29,57,43,.16);transform:translateX(105%);transition:transform .2s ease;background:#fff; }
.settings-rail.open { transform:translateX(0); }
.close-preferences { position:absolute;top:17px;right:18px;padding:6px 9px;border:1px solid #cbdcd1;border-radius:9px;background:#fff;color:#2b7051;font-size:12px;cursor:pointer; }
@media (max-width: 1180px) { .agent-shell { grid-template-columns: 220px minmax(0, 1fr); } }
@media (max-width: 760px) { .conversation-workspace { padding:0 14px; }.workspace-header{min-height:68px}.workspace-header h1{max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.session-state{display:none}.header-actions{gap:7px}.console-trigger{padding:6px 7px;font-size:11px}.conversation-thread{padding:18px 0 24px}.composer-dock{padding-bottom:12px}.planning-context{padding-top:5px}.planning-context>span{display:none}.planning-context .context-settings{display:inline-block}.settings-rail{width:100vw}.route-response{margin-top:18px} }
.console-trigger, .console-rail-button, .settings-form select, .profile-setting input, .workspace-switch select { border-radius: 10px; }
.session-card { border-radius: 12px; background: #fafcfb; }
.session-card strong { font-family: "Microsoft YaHei", "微软雅黑", sans-serif; }
</style>
