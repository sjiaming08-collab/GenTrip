<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Compass, Eye, EyeOff, LockKeyhole, Mail, Route, ShieldCheck, UserRound } from '@lucide/vue'
import { login, register, type AuthIdentity } from '../api'

const emit = defineEmits<{ authenticated: [identity: AuthIdentity] }>()
const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const displayName = ref('')
const showPassword = ref(false)
const busy = ref(false)
const error = ref('')

const isLogin = computed(() => mode.value === 'login')

function selectMode(nextMode: 'login' | 'register') {
  mode.value = nextMode
  error.value = ''
}

function personalSpaceName() {
  const fallback = email.value.split('@', 1)[0] || '我的'
  return `${displayName.value.trim() || fallback}的旅行空间`
}

function presentError(reason: any) {
  const detail = reason?.response?.data?.detail
  if (detail === 'invalid_credentials') return '邮箱或密码不正确，请重新输入。'
  if (detail === 'email_already_registered') return '该邮箱已注册，可以直接登录。'
  if (detail === 'password_length_must_be_12_to_128') return '密码长度需要在 12 到 128 个字符之间。'
  if (reason?.response?.status === 422) return '请检查邮箱格式和密码长度。'
  return typeof detail === 'string' && /[\u4e00-\u9fff]/.test(detail)
    ? detail
    : '暂时无法完成登录，请稍后重试。'
}

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const identity = isLogin.value
      ? await login(email.value, password.value)
      : await register(email.value, password.value, displayName.value, personalSpaceName())
    emit('authenticated', identity)
  } catch (reason: any) {
    error.value = presentError(reason)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel" aria-labelledby="auth-title">
      <header class="brand-heading">
        <div class="brand-lockup">
          <span class="brand-mark" aria-hidden="true">
            <Compass :size="24" stroke-width="2" />
          </span>
          <strong>GenTrip</strong>
        </div>
        <p class="brand-promise">
          <Route :size="15" stroke-width="2" aria-hidden="true" />
          <span>从出行想法到可执行路线</span>
        </p>
      </header>

      <div class="auth-heading">
        <h1 id="auth-title">{{ isLogin ? '欢迎回来' : '创建旅行账户' }}</h1>
        <p>{{ isLogin ? '登录后继续规划你的行程' : '保存路线，并在多轮对话中继续调整' }}</p>
      </div>

      <div class="mode-switch" role="tablist" aria-label="账户操作">
        <button type="button" role="tab" :aria-selected="isLogin" :class="{ active: isLogin }" @click="selectMode('login')">登录</button>
        <button type="button" role="tab" :aria-selected="!isLogin" :class="{ active: !isLogin }" @click="selectMode('register')">注册</button>
      </div>

      <form @submit.prevent="submit">
        <label v-if="!isLogin">
          <span>称呼</span>
          <div class="input-wrap">
            <UserRound :size="17" />
            <input v-model.trim="displayName" maxlength="80" autocomplete="name" placeholder="例如：小李" required>
          </div>
        </label>

        <label>
          <span>邮箱</span>
          <div class="input-wrap">
            <Mail :size="17" />
            <input v-model.trim="email" type="email" autocomplete="email" placeholder="name@example.com" required>
          </div>
        </label>

        <label>
          <span>密码</span>
          <div class="input-wrap">
            <LockKeyhole :size="17" />
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              minlength="12"
              :autocomplete="isLogin ? 'current-password' : 'new-password'"
              :placeholder="isLogin ? '输入密码' : '至少 12 个字符'"
              required
            >
            <button
              class="password-toggle"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              :title="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" :size="17" />
              <Eye v-else :size="17" />
            </button>
          </div>
        </label>

        <p v-if="error" class="error" role="alert">{{ error }}</p>

        <button class="submit-button" type="submit" :disabled="busy">
          <span>{{ busy ? '正在处理…' : isLogin ? '登录' : '创建账户' }}</span>
          <ArrowRight v-if="!busy" :size="17" />
        </button>
      </form>

      <p class="privacy-note">
        <ShieldCheck :size="15" aria-hidden="true" />
        <span>账户用于安全保存你的路线与会话记录</span>
      </p>
    </section>
  </main>
</template>

<style scoped>
:global(*) { box-sizing: border-box; letter-spacing: 0; }
:global(html), :global(body), :global(#app) { min-width: 320px; min-height: 100%; }
:global(body) { margin: 0; }
button, input { font: inherit; }

.auth-page {
  position: relative;
  width: 100%;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 32px 20px;
  overflow: hidden;
  background: #dfe6e1 url("../assets/auth-city.jpg") center / cover no-repeat;
  color: #203129;
  font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
}
.auth-page::before {
  position: absolute;
  inset: 0;
  background: rgba(235, 241, 237, .58);
  content: "";
}

.auth-panel {
  position: relative;
  z-index: 1;
  width: min(420px, 100%);
  padding: 38px 38px 30px;
  border: 1px solid rgba(255, 255, 255, .82);
  border-radius: 8px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 24px 70px rgba(28, 45, 36, .2);
  backdrop-filter: blur(14px);
}

.brand-heading { display: grid; justify-items: center; }
.brand-lockup { display: flex; align-items: center; gap: 11px; }
.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #147554;
  color: #fff;
  box-shadow: 0 6px 18px rgba(20, 117, 84, .2);
}
.brand-lockup strong { font-size: 22px; line-height: 1; }
.brand-promise {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: 15px 0 0;
  color: #4b7562;
  font-size: 12px;
  font-weight: 700;
}
.brand-promise svg { flex: 0 0 auto; color: #d56747; }

.auth-heading { margin-top: 38px; text-align: center; }
.auth-heading h1 { margin: 0; font-size: 26px; line-height: 1.35; }
.auth-heading p { margin: 9px 0 0; color: #718078; font-size: 13px; line-height: 1.6; }

.mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin: 26px 0 22px;
  padding: 4px;
  border: 1px solid #dbe3de;
  border-radius: 8px;
  background: #f2f5f3;
}
.mode-switch button {
  min-height: 38px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #74837b;
  cursor: pointer;
  font-weight: 700;
}
.mode-switch button.active {
  background: #fff;
  color: #176f51;
  box-shadow: 0 1px 5px rgba(36, 57, 46, .1);
}

form { display: grid; gap: 17px; }
label { display: grid; gap: 7px; color: #425b4f; font-size: 12px; font-weight: 700; }
.input-wrap {
  height: 46px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border: 1px solid #cfdad3;
  border-radius: 8px;
  background: #fbfcfb;
  color: #789087;
  transition: border-color .15s, box-shadow .15s, background .15s;
}
.input-wrap:focus-within {
  border-color: #3a8e6c;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(27, 125, 88, .1);
  color: #277657;
}
input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; color: #273a30; font-size: 14px; }
input::placeholder { color: #9aaba2; }
.password-toggle {
  width: 28px;
  height: 28px;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #71867b;
  cursor: pointer;
}
.password-toggle:hover { background: #edf3ef; color: #176f51; }
.error {
  margin: -3px 0 0;
  padding: 9px 10px;
  border: 1px solid #efccc4;
  border-radius: 8px;
  background: #fff6f3;
  color: #a04435;
  font-size: 12px;
  line-height: 1.5;
}
.submit-button {
  min-height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  margin-top: 3px;
  border: 1px solid #147554;
  border-radius: 8px;
  background: #147554;
  color: #fff;
  cursor: pointer;
  font-weight: 700;
  transition: border-color .15s, background .15s, transform .15s;
}
.submit-button:not(:disabled):hover {
  border-color: #0c6346;
  background: #0c6346;
  transform: translateY(-1px);
}
.submit-button:disabled { cursor: wait; opacity: .68; }

.privacy-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 20px 0 0;
  color: #7b8982;
  font-size: 11px;
  line-height: 1.5;
}
.privacy-note svg { flex: 0 0 auto; color: #43866a; }

@media (max-width: 520px) {
  .auth-page { align-items: center; padding: 18px; }
  .auth-panel { padding: 32px 22px 26px; }
  .auth-heading { margin-top: 34px; }
  .auth-heading h1 { font-size: 24px; }
}

@media (prefers-reduced-motion: reduce) {
  .submit-button { transition: none; }
}
</style>
