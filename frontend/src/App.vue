<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import RoutePlanner from './components/RoutePlanner.vue'
import ItineraryTimeline from './components/ItineraryTimeline.vue'
import MapView from './components/MapView.vue'
import FeedbackPanel from './components/FeedbackPanel.vue'
import ProgressBar from './components/ProgressBar.vue'
import { getSession, listSessions, submitFeedback as saveFeedback, updateSessionTitle } from './api'
import { useRoutePlan } from './composables/useRoutePlan'
import type { FeedbackRequest, RoutePlanRequest, RoutePlanResult, RouteStop, SessionDetail } from './types'

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
}

const SETTINGS_STORAGE_KEY = 'gentrip-agent-settings'

const {
  loading,
  currentPhase,
  currentRoute,
  selectedResult,
  routeResults,
  presentation,
  error,
  submitQuery,
  cancelPlanning,
  selectResult,
  resetPlanningState,
  restoreRoute,
} = useRoutePlan()

const selectedStop = ref<RouteStop | null>(null)
const sessionId = ref<string | null>(null)
const historySessions = ref<HistorySession[]>([])
const messages = ref<ChatMessage[]>([])
const conversationThread = ref<HTMLElement | null>(null)
const editingTitle = ref(false)
const titleDraft = ref('')
const defaultDistrict = ref('黄浦区')
const defaultBudget = ref(150)
const defaultDuration = ref(180)
const profileId = ref('local-traveler')
const useDefaults = ref(true)

const selectedStopIndex = computed(() => {
  if (!selectedStop.value || !selectedResult.value) return -1
  return selectedResult.value.route.stops.findIndex((stop) => stop.poi_id === selectedStop.value?.poi_id)
})

const replyType = computed(() => currentRoute.value?.reply_type ?? 'route')
const isDiff = computed(() => replyType.value === 'diff')
const isReject = computed(() => replyType.value === 'reject')
const isDegraded = computed(() => replyType.value === 'degraded_route')
const suggestionMoves = computed(() => currentRoute.value?.meta?.next_suggested_user_moves ?? [])
const activeSession = computed(() => historySessions.value.find((item) => item.sessionId === sessionId.value))
const activeTitle = computed(() => activeSession.value?.title || '新路线对话')
const PLAN_PHASES = [
  'turn_orchestrate', 'constraint_extract', 'geo_resolve', 'poi_retrieve',
  'route_generate', 'route_validate', 'route_evaluate', 'route_present',
]

function nowTime() {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function buildRequest(request: RoutePlanRequest): RoutePlanRequest {
  const query = request.query.trim()
  if (!useDefaults.value) return { ...request, query, user_id: profileId.value || undefined }

  const additions: string[] = []
  if (!/(徐汇|静安|黄浦|浦东).{0,2}区?/.test(query)) additions.push(defaultDistrict.value)
  if (!/\d+\s*(元|块)/.test(query)) additions.push(`人均${defaultBudget.value}元`)
  if (!/\d+\s*(小时|h|分钟)/i.test(query) && !/半天/.test(query)) additions.push(`${defaultDuration.value / 60}小时`)

  return {
    ...request,
    query: additions.length ? `${query}，${additions.join('，')}` : query,
    user_id: profileId.value || undefined,
  }
}

function addMessage(role: ChatMessage['role'], text: string) {
  messages.value.push({ id: crypto.randomUUID(), role, text, time: nowTime() })
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

function saveHistory(query: string) {
  if (!currentRoute.value?.session_id) return
  const existing = historySessions.value.find((entry) => entry.sessionId === currentRoute.value?.session_id)
  const item: HistorySession = {
    sessionId: currentRoute.value.session_id,
    title: existing?.title || query,
    summary: presentation.value?.summary || selectedResult.value?.route.summary || '已生成路线',
    updatedAt: nowTime(),
    routeCount: routeResults.value.length,
  }
  historySessions.value = [item, ...historySessions.value.filter((entry) => entry.sessionId !== item.sessionId)].slice(0, 12)
}

async function handleSubmit(request: RoutePlanRequest) {
  selectedStop.value = null
  const enriched = buildRequest({ ...request, session_id: request.session_id || sessionId.value || undefined })
  addMessage('user', request.query.trim())
  await submitQuery(enriched)

  if (currentRoute.value?.session_id) {
    sessionId.value = currentRoute.value.session_id
    addMessage('assistant', presentation.value?.summary || '路线已生成，已在下方展示。')
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
      if (assistantText) {
        result.push({
          id: `assistant-${turn.turn_id}`,
          role: 'assistant',
          text: assistantText,
          time: new Date(turn.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        })
      }
      return result
    })
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

function handleSelectResult(result: RoutePlanResult) {
  selectedStop.value = null
  selectResult(result)
}

function handleSelectStop(stop: RouteStop) {
  selectedStop.value = stop
}

function handleSelectPoi(poiId: string) {
  const stop = selectedResult.value?.route.stops.find((item) => item.poi_id === poiId)
  if (stop) selectedStop.value = stop
}

async function handleFeedback(feedback: FeedbackRequest) {
  await saveFeedback({
    ...feedback,
    session_id: currentRoute.value?.session_id ?? sessionId.value ?? '',
  })
}

function handleSuggestion(query: string) {
  void handleSubmit({ query, session_id: sessionId.value ?? undefined })
}

onMounted(async () => {
  try {
    const savedSettings = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) || '{}')
    defaultDistrict.value = savedSettings.defaultDistrict || defaultDistrict.value
    defaultBudget.value = savedSettings.defaultBudget || defaultBudget.value
    defaultDuration.value = savedSettings.defaultDuration || defaultDuration.value
    profileId.value = savedSettings.profileId || profileId.value
    useDefaults.value = savedSettings.useDefaults ?? useDefaults.value
  } catch { /* Use the built-in defaults when browser preferences are unavailable. */ }
  try { await refreshHistory() } catch { historySessions.value = [] }
})

watch([defaultDistrict, defaultBudget, defaultDuration, profileId, useDefaults], () => {
  localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
    defaultDistrict: defaultDistrict.value,
    defaultBudget: defaultBudget.value,
    defaultDuration: defaultDuration.value,
    profileId: profileId.value,
    useDefaults: useDefaults.value,
  }))
  void refreshHistory()
})

watch(
  [() => messages.value.length, loading, currentRoute],
  () => scrollToLatestMessage(),
  { flush: 'post' },
)
</script>

<template>
  <div class="agent-shell">
    <aside class="history-rail">
      <div class="brand-lockup">
        <div class="brand-mark">G</div>
        <div>
          <strong>GenTrip</strong>
          <span>城市路线 Agent</span>
        </div>
      </div>

      <button class="new-session" type="button" @click="startNewSession">新建路线对话</button>

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
        <span>路线引擎在线</span>
      </div>
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
        <div class="session-state">
          <span class="state-dot" />
          {{ loading ? '规划中' : '可继续调整' }}
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

        <article v-for="message in messages" :key="message.id" class="message" :class="`${message.role}-message`">
          <span v-if="message.role === 'assistant'" class="avatar">G</span>
          <div class="message-bubble">
            <p class="message-name">{{ message.role === 'assistant' ? 'GenTrip' : '你' }} · {{ message.time }}</p>
            <p>{{ message.text }}</p>
          </div>
        </article>

        <article v-if="loading" class="assistant-progress">
          <div class="progress-copy">
            <span class="avatar">G</span>
            <div><strong>正在规划路线</strong><span>{{ currentPhase }}</span></div>
          </div>
          <ProgressBar :current-phase="currentPhase" :phases="PLAN_PHASES" @cancel="cancelPlanning" />
        </article>

        <p v-if="error" class="error-state">{{ error }}</p>

        <section v-if="currentRoute && !loading" class="route-response">
          <div v-if="isDegraded" class="degraded-notice">已按可执行性放宽部分条件，以下路线仍可直接出发。</div>

          <div v-if="isReject && presentation" class="reply-summary">
            <p class="eyebrow">路线助手</p>
            <h2>{{ presentation.title }}</h2>
            <p>{{ presentation.summary }}</p>
            <div class="suggestion-row">
              <button v-for="move in suggestionMoves" :key="move" type="button" @click="handleSuggestion(move)">{{ move }}</button>
            </div>
          </div>

          <template v-else>
            <div v-if="presentation" class="reply-summary">
              <p class="eyebrow">路线建议</p>
              <h2>{{ presentation.title }}</h2>
              <p>{{ presentation.summary }}</p>
              <ul v-if="presentation.highlights.length">
                <li v-for="item in presentation.highlights" :key="item">{{ item }}</li>
              </ul>
            </div>

            <div v-if="isDiff && presentation" class="diff-strip">{{ presentation.summary }}</div>

            <div v-if="currentRoute.assumptions.length" class="assumption-strip">
              <strong>本次默认</strong>
              <span v-for="item in currentRoute.assumptions" :key="`${item.slot}-${item.assumed_value}`">{{ item.message }}</span>
            </div>

            <div v-if="routeResults.length > 1" class="route-tabs" aria-label="备选路线">
              <button
                v-for="result in routeResults"
                :key="result.route.plan_id"
                type="button"
                :class="{ active: selectedResult?.route.plan_id === result.route.plan_id }"
                @click="handleSelectResult(result)"
              >
                方案 {{ result.rank }} <span>{{ result.scores.final.toFixed(2) }}</span>
              </button>
            </div>

            <div class="result-layout">
              <ItineraryTimeline :result="selectedResult" :current-stop-index="selectedStopIndex" @select-stop="handleSelectStop" />
              <MapView :stops="selectedResult?.route.stops" :selected-stop-id="selectedStop?.poi_id ?? null" @select-poi="handleSelectPoi" />
            </div>
            <FeedbackPanel :result="selectedResult" :session-id="currentRoute.session_id" @submit-feedback="handleFeedback" />
          </template>
        </section>
      </section>

      <div class="composer-dock">
        <RoutePlanner :is-loading="loading" @submit="handleSubmit" />
      </div>
    </main>

    <aside class="settings-rail">
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
          常用区域
          <select v-model="defaultDistrict" :disabled="!useDefaults">
            <option>黄浦区</option><option>徐汇区</option><option>静安区</option><option>浦东新区</option>
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
    </aside>
  </div>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(html), :global(body), :global(#app) { height: 100%; }
:global(body) { margin: 0; min-width: 320px; overflow: hidden; background: #f1f8f3; color: #18362a; font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
:global(button), :global(input), :global(select), :global(textarea) { font: inherit; }

.agent-shell { height: 100dvh; min-height: 0; display: grid; grid-template-columns: 272px minmax(0, 1fr) 292px; overflow: hidden; background: #f1f8f3; }
.history-rail, .settings-rail { min-height: 0; height: 100%; overflow-y: auto; background: #ffffff; border-color: #dcebe1; }
.history-rail { display: flex; flex-direction: column; padding: 24px 16px 18px; border-right: 1px solid #dcebe1; }
.settings-rail { padding: 28px 22px; border-left: 1px solid #dcebe1; }
.brand-lockup { display: flex; gap: 10px; align-items: center; padding: 0 6px 24px; }
.brand-mark, .avatar { display: inline-flex; align-items: center; justify-content: center; background: #167b59; color: #fff; font-family: Georgia, serif; font-weight: 700; }
.brand-mark { width: 32px; height: 32px; border-radius: 8px; font-size: 18px; }
.brand-lockup strong { display: block; font-size: 17px; letter-spacing: .02em; }
.brand-lockup span { display: block; margin-top: 2px; color: #749184; font-size: 12px; }
.new-session { width: 100%; padding: 10px 12px; border: 1px solid #167b59; border-radius: 7px; background: #167b59; color: #fff; cursor: pointer; font-weight: 700; }
.new-session:hover { background: #0e6748; }
.rail-heading { display: flex; justify-content: space-between; align-items: center; margin: 28px 6px 10px; color: #608071; font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.count { display: inline-flex; min-width: 20px; justify-content: center; padding: 2px 6px; border-radius: 999px; background: #e8f4ec; color: #177657; }
.session-list { display: grid; gap: 5px; overflow-y: auto; }
.session-item { width: 100%; display: grid; gap: 5px; padding: 11px 10px; text-align: left; border: 1px solid transparent; border-radius: 7px; background: transparent; color: #24483a; cursor: pointer; }
.session-item:hover, .session-item.selected { background: #edf8f0; border-color: #cce7d4; }
.session-item strong, .session-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item strong { font-size: 13px; }
.session-item span { color: #6e8b7d; font-size: 12px; }
.session-item small { color: #94aa9f; font-size: 11px; }
.empty-history { margin: 16px 8px; color: #91a79b; font-size: 12px; line-height: 1.6; }
.rail-footer { display: flex; gap: 8px; align-items: center; margin-top: auto; padding: 14px 7px 0; color: #688477; font-size: 12px; }
.presence-dot, .state-dot { width: 8px; height: 8px; border-radius: 50%; background: #38a879; box-shadow: 0 0 0 3px #e6f5eb; }

.conversation-workspace { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 0 32px; }
.workspace-header { position: relative; z-index: 1; flex: 0 0 auto; min-height: 96px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #dcebe1; background: #f1f8f3; }
.eyebrow { margin: 0 0 6px; color: #4a9171; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.workspace-header h1, .settings-header h2, .reply-summary h2 { margin: 0; font-family: Georgia, "Noto Serif SC", serif; font-weight: 600; }
.workspace-header h1 { font-size: 23px; }
.title-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
.title-edit { padding: 3px 0; border: 0; background: transparent; color: #398364; font-size: 12px; cursor: pointer; }
.title-edit:hover { color: #135e42; text-decoration: underline; }
.title-input { width: min(360px, 58vw); padding: 2px 0 4px; border: 0; border-bottom: 1px solid #57a77d; background: transparent; color: #18362a; font-family: Georgia, "Noto Serif SC", serif; font-size: 23px; font-weight: 600; outline: none; }
.session-state { display: flex; align-items: center; gap: 9px; color: #5e7f70; font-size: 13px; }
.conversation-thread { width: min(100%, 850px); min-height: 0; flex: 1 1 auto; margin: 0 auto; overflow-y: auto; overscroll-behavior: contain; padding: 34px 0; scroll-behavior: smooth; }
.message { display: flex; gap: 11px; margin-bottom: 20px; }
.assistant-message { max-width: 82%; }
.user-message { justify-content: flex-end; }
.avatar { flex: 0 0 30px; height: 30px; border-radius: 50%; font-size: 14px; }
.message-bubble { max-width: 100%; padding: 12px 14px; border: 1px solid #dcebe1; border-radius: 8px; background: #fff; color: #2d4c3e; line-height: 1.65; }
.user-message .message-bubble { max-width: 72%; border-color: #bfe1c9; background: #dff4e5; }
.message-bubble p { margin: 0; }
.message-name { margin-bottom: 4px !important; color: #729083; font-size: 11px; }
.welcome-message .message-bubble { padding: 15px 17px; }
.assistant-progress { margin: 18px 0; padding: 16px; border: 1px solid #cfe8d7; border-radius: 8px; background: #f9fdf9; }
.progress-copy { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.progress-copy strong, .progress-copy span { display: block; }
.progress-copy strong { font-size: 14px; }.progress-copy span { margin-top: 3px; color: #739184; font-size: 12px; }
.error-state { margin: 16px 0; padding: 11px 13px; border-left: 3px solid #d3675d; background: #fff7f5; color: #9c443d; font-size: 13px; }
.route-response { margin-top: 24px; }
.reply-summary { padding: 20px 0; border-top: 1px solid #dcebe1; border-bottom: 1px solid #dcebe1; }
.reply-summary h2 { font-size: 24px; }.reply-summary > p:not(.eyebrow) { margin: 9px 0 0; color: #537265; line-height: 1.65; }
.reply-summary ul { display: grid; gap: 7px; margin: 14px 0 0; padding: 0; list-style: none; color: #456556; font-size: 14px; }
.reply-summary li::before { content: '•'; margin-right: 8px; color: #2a9567; }
.assumption-strip { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; margin: 18px 0; color: #547366; font-size: 12px; }
.assumption-strip strong { margin-right: 4px; color: #2b5946; }.assumption-strip span { padding: 5px 8px; border-radius: 999px; background: #e9f6ed; }
.degraded-notice, .diff-strip { margin: 16px 0; padding: 10px 12px; border-radius: 7px; font-size: 13px; }
.degraded-notice { background: #fff8e8; color: #906b22; border: 1px solid #f0dc9f; }.diff-strip { background: #eef8f1; color: #317255; }
.suggestion-row, .route-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.suggestion-row button, .route-tabs button { border: 1px solid #c8e4d1; border-radius: 7px; padding: 7px 10px; background: #fff; color: #2a694d; cursor: pointer; font-size: 13px; }
.suggestion-row button:hover, .route-tabs button.active { border-color: #16805a; background: #e9f7ed; color: #116b4a; }
.route-tabs button span { margin-left: 5px; color: #6d8f7e; font-size: 11px; }.result-layout { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(270px, .95fr); gap: 14px; margin-top: 20px; }
.composer-dock { position: relative; z-index: 1; flex: 0 0 auto; width: min(100%, 850px); margin: auto; padding: 14px 0 20px; background: #f1f8f3; }

.settings-header { margin-bottom: 22px; }.settings-header h2 { font-size: 19px; }.setting-switch { display: flex; justify-content: space-between; gap: 10px; padding: 13px 0; border-top: 1px solid #e0eee4; border-bottom: 1px solid #e0eee4; cursor: pointer; }.setting-switch strong, .setting-switch small { display: block; }.setting-switch strong { font-size: 13px; }.setting-switch small { margin-top: 4px; color: #829c90; font-size: 11px; line-height: 1.45; }.setting-switch input { width: 34px; accent-color: #167b59; }
.settings-form { display: grid; gap: 14px; padding-top: 18px; transition: opacity .2s; }.settings-form.muted { opacity: .45; }.settings-form label, .profile-setting { display: grid; gap: 7px; color: #567768; font-size: 12px; font-weight: 700; }.settings-form select, .profile-setting input { width: 100%; padding: 9px 10px; border: 1px solid #cfe4d6; border-radius: 6px; background: #fbfefc; color: #28523e; outline: none; }.settings-form select:focus, .profile-setting input:focus { border-color: #3b9b70; box-shadow: 0 0 0 3px #e6f5ea; }.settings-divider { height: 1px; margin: 24px 0 18px; background: #e0eee4; }.session-card { display: grid; gap: 7px; margin-top: 26px; padding: 13px; border: 1px solid #d9ebdf; border-radius: 7px; background: #f7fcf8; }.session-card span, .session-card small { color: #789387; font-size: 11px; }.session-card strong { font-family: ui-monospace, monospace; color: #29664b; font-size: 13px; }

@media (max-width: 1180px) { .agent-shell { grid-template-columns: 236px minmax(0, 1fr); }.settings-rail { display: none; }.conversation-workspace { padding: 0 24px; } }
@media (max-width: 760px) { :global(body) { overflow: auto; }.agent-shell { height: auto; min-height: 100dvh; display: block; overflow: visible; }.history-rail { min-height: auto; height: auto; padding: 16px; overflow: visible; border-right: 0; border-bottom: 1px solid #dcebe1; }.brand-lockup { padding-bottom: 14px; }.new-session { width: auto; }.rail-heading { margin-top: 18px; }.session-list { grid-auto-flow: column; grid-auto-columns: minmax(190px, 72%); overflow-x: auto; }.rail-footer { display: none; }.conversation-workspace { height: 100dvh; padding: 0 16px; }.workspace-header { min-height: 76px; }.workspace-header h1 { font-size: 19px; }.conversation-thread { padding-top: 22px; }.assistant-message, .user-message .message-bubble { max-width: 88%; }.result-layout { grid-template-columns: 1fr; }.composer-dock { padding-bottom: 14px; } }
</style>
