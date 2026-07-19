<script setup lang="ts">
import { ref } from 'vue'
import { login, register, type AuthIdentity } from '../api'

const emit = defineEmits<{ authenticated: [identity: AuthIdentity] }>()
const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const displayName = ref('')
const tenantName = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const identity = mode.value === 'login'
      ? await login(email.value, password.value)
      : await register(email.value, password.value, displayName.value, tenantName.value)
    emit('authenticated', identity)
  } catch (reason: any) {
    error.value = reason?.response?.data?.detail === 'invalid_credentials'
      ? 'Email or password is incorrect.'
      : reason?.response?.data?.detail === 'email_already_registered'
        ? 'This email is already registered.'
        : reason?.response?.data?.detail || 'Unable to sign in. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <form class="auth-panel" @submit.prevent="submit">
      <div class="mark">G</div>
      <p class="eyebrow">GenTrip workspace</p>
      <h1>{{ mode === 'login' ? 'Sign in' : 'Create workspace' }}</h1>
      <p class="intro">Your routes, history, and preferences stay inside your workspace.</p>
      <label>Email<input v-model.trim="email" type="email" autocomplete="email" required></label>
      <label>Password<input v-model="password" type="password" minlength="12" autocomplete="current-password" required></label>
      <template v-if="mode === 'register'">
        <label>Display name<input v-model.trim="displayName" maxlength="80" autocomplete="name"></label>
        <label>Workspace name<input v-model.trim="tenantName" maxlength="80"></label>
      </template>
      <p v-if="error" class="error">{{ error }}</p>
      <button type="submit" :disabled="busy">{{ busy ? 'Working...' : mode === 'login' ? 'Sign in' : 'Create account' }}</button>
      <button class="switch" type="button" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? 'Create a new workspace' : 'Use an existing account' }}
      </button>
    </form>
  </main>
</template>

<style scoped>
.auth-page { min-height: 100dvh; display: grid; place-items: center; padding: 24px; background: #edf5ef; color: #18362a; font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.auth-panel { width: min(100%, 390px); display: grid; gap: 14px; padding: 28px; border: 1px solid #d9e9de; border-radius: 8px; background: #fff; box-shadow: 0 16px 42px rgb(25 73 48 / 10%); }
.mark { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 8px; background: #167b59; color: #fff; font: 700 20px Georgia, serif; }
.eyebrow { margin: 8px 0 -7px; color: #4a9171; font-size: 11px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }.auth-panel h1 { margin: 0; font: 600 28px Georgia, "Noto Serif SC", serif; }.intro { margin: -5px 0 4px; color: #668376; font-size: 13px; line-height: 1.55; }
label { display: grid; gap: 6px; color: #496c5c; font-size: 12px; font-weight: 700; } input { width: 100%; padding: 10px; border: 1px solid #c9dfd0; border-radius: 6px; color: #18362a; outline: none; } input:focus { border-color: #298763; box-shadow: 0 0 0 3px #e3f2e8; }.error { margin: 0; color: #aa463e; font-size: 12px; }
button { min-height: 40px; border: 1px solid #167b59; border-radius: 6px; background: #167b59; color: #fff; cursor: pointer; font-weight: 700; } button:disabled { cursor: wait; opacity: .65; }.switch { min-height: 28px; border: 0; background: transparent; color: #28785a; font-size: 12px; font-weight: 600; }
</style>
