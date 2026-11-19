<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
      <div>
        <h1 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Sign in to WebHDP
        </h1>
      </div>

      <form v-if="step === 'credentials'" class="mt-8 space-y-6" :aria-busy="loading" @submit.prevent="handleLogin">
        <div v-if="error" role="alert" data-testid="login-error" class="bg-red-50 border border-red-400 text-red-700 px-4 py-3 rounded">
          {{ error }}
        </div>

        <div class="space-y-4">
          <div>
            <label for="email" class="block text-sm font-medium text-gray-900">Email address or demo username</label>
            <input
              id="email"
              ref="identifierField"
              v-model.trim="form.email"
              data-testid="login-email"
              name="email"
              type="text"
              inputmode="email"
              autocomplete="username"
              autocapitalize="none"
              :spellcheck="false"
              required
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm"
              placeholder="Email address or demo username"
            />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-gray-900">Password</label>
            <input
              id="password"
              v-model="form.password"
              data-testid="login-password"
              name="password"
              type="password"
              autocomplete="current-password"
              required
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm"
            />
          </div>
        </div>

        <div>
          <button
            type="submit"
            :disabled="loading"
            data-testid="login-submit"
            class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
          >
            {{ loading ? 'Signing in...' : 'Sign in' }}
          </button>
        </div>

        <div class="text-center">
          <router-link to="/register" class="text-indigo-600 hover:text-indigo-500">
            Create an account
          </router-link>
          <span class="mx-2 text-gray-300">|</span>
          <router-link :to="{ path: '/register', query: { resend: '1' } }" class="text-indigo-700 hover:text-indigo-900">
            Resend verification
          </router-link>
        </div>
      </form>

      <form v-else class="mt-8 space-y-6" :aria-busy="loading" @submit.prevent="handleVerifyCode">
        <div v-if="error" role="alert" data-testid="login-error" class="bg-red-50 border border-red-400 text-red-700 px-4 py-3 rounded">
          {{ error }}
        </div>

        <div v-if="successMessage" role="status" data-testid="login-success" class="bg-green-50 border border-green-300 text-green-700 px-4 py-3 rounded">
          {{ successMessage }}
        </div>

        <div class="space-y-2">
          <p class="text-sm text-gray-600 text-center">
            <span v-if="mfaMode === 'email'">Enter the verification code sent to {{ mfaChallenge.maskedEmail || 'your email address' }}.</span>
            <span v-else>Enter one of your saved recovery codes.</span>
          </p>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              :aria-pressed="mfaMode === 'email'"
              class="rounded-md border px-3 py-2 text-sm font-medium"
              :class="mfaMode === 'email' ? 'border-indigo-600 bg-indigo-50 text-indigo-700' : 'border-gray-300 text-gray-700 hover:bg-gray-50'"
              @click="mfaMode = 'email'"
            >
              Email code
            </button>
            <button
              type="button"
              data-testid="login-use-recovery-code"
              :aria-pressed="mfaMode === 'recovery'"
              class="rounded-md border px-3 py-2 text-sm font-medium"
              :class="mfaMode === 'recovery' ? 'border-indigo-600 bg-indigo-50 text-indigo-700' : 'border-gray-300 text-gray-700 hover:bg-gray-50'"
              @click="mfaMode = 'recovery'"
            >
              Recovery code
            </button>
          </div>
          <label :for="mfaMode === 'email' ? 'mfa-code' : 'recovery-code'" class="sr-only">
            {{ mfaMode === 'email' ? 'Verification code' : 'Recovery code' }}
          </label>
          <input
            v-if="mfaMode === 'email'"
            id="mfa-code"
            ref="codeField"
            v-model="code"
            data-testid="login-mfa-code"
            name="code"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            class="appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm text-center tracking-widest"
            placeholder="000000"
          />
          <input
            v-else
            id="recovery-code"
            v-model="recoveryCode"
            data-testid="login-recovery-code"
            name="recovery-code"
            type="text"
            autocomplete="one-time-code"
            required
            class="appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm text-center tracking-widest"
            placeholder="ABCD-EFGH-IJKL"
          />
        </div>

        <div>
          <button
            type="submit"
            :disabled="loading"
            data-testid="login-mfa-submit"
            class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
          >
            {{ loading ? 'Verifying...' : (mfaMode === 'email' ? 'Verify code' : 'Use recovery code') }}
          </button>
        </div>

        <div class="flex items-center justify-between text-sm">
          <button
            type="button"
            data-testid="login-back"
            class="text-gray-600 hover:text-gray-900"
            @click="returnToCredentials"
          >
            Back
          </button>
          <button
            v-if="mfaMode === 'email'"
            type="button"
            :disabled="resending"
            data-testid="login-resend-code"
            class="text-indigo-600 hover:text-indigo-500 disabled:opacity-50"
            @click="handleResendCode"
          >
            {{ resending ? 'Sending...' : 'Resend code' }}
          </button>
        </div>
      </form>

      <LegalLinks />
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { linkLoginDestination } from '@/utils/webhdpLink'
import { useAuthStore } from '@/stores/auth'
import LegalLinks from '@/components/legal/LegalLinks.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const identifierField = ref(null)
const codeField = ref(null)

const form = ref({
  email: '',
  password: ''
})

const step = ref('credentials')
const mfaChallenge = ref({
  token: '',
  maskedEmail: '',
  developmentCode: ''
})
const mfaMode = ref('email')
const code = ref('')
const recoveryCode = ref('')
const loading = ref(false)
const resending = ref(false)
const error = ref('')
const successMessage = ref('')

const finishLogin = () => {
  const destination = linkLoginDestination(route.query?.redirect, '/dashboard')
  router.push(authStore.user?.model_publication_only && !destination.startsWith('/model-publication')
    ? '/model-publication'
    : destination)
}

const resolveLoginErrorMessage = (err) => {
  if (err?.error?.code === 'EMAIL_NOT_VERIFIED') {
    return 'Verify your email before signing in. You can request a new link below.'
  }
  if (typeof err?.error === 'string' && err.error.trim()) {
    return err.error
  }
  if (typeof err?.error?.message === 'string' && err.error.message.trim()) {
    return err.error.message
  }
  if (typeof err?.message === 'string' && err.message.trim()) {
    return err.message
  }
  return 'Login failed. Please check your credentials.'
}

const shouldReturnToCredentials = (err) => {
  const codeValue = err?.error?.code
  const message = resolveLoginErrorMessage(err).toLowerCase()
  return ['MFA_CHALLENGE_INVALID', 'MFA_CHALLENGE_LOCKED'].includes(codeValue) || message.includes('sign in again')
}

const returnToCredentials = () => {
  step.value = 'credentials'
  mfaChallenge.value = { token: '', maskedEmail: '', developmentCode: '' }
  mfaMode.value = 'email'
  code.value = ''
  recoveryCode.value = ''
  successMessage.value = ''
  error.value = ''
  nextTick(() => identifierField.value?.focus())
}

const applyMfaChallenge = (data) => {
  const developmentCode = String(data?.development_mfa_code || '')
  mfaChallenge.value = {
    token: data.mfa_token,
    maskedEmail: data.masked_email,
    developmentCode
  }
  code.value = developmentCode
  recoveryCode.value = ''
  mfaMode.value = 'email'
  successMessage.value = developmentCode
    ? `Development login code: ${developmentCode}`
    : 'Verification code sent.'
}

const handleLogin = async () => {
  if (loading.value) return
  loading.value = true
  error.value = ''
  successMessage.value = ''

  try {
    const response = await authStore.login(form.value.email, form.value.password)
    if (response?.data?.mfa_required) {
      applyMfaChallenge(response.data)
      step.value = 'mfa'
      await nextTick()
      codeField.value?.focus()
      return
    }
    finishLogin()
  } catch (err) {
    error.value = resolveLoginErrorMessage(err)
  } finally {
    loading.value = false
  }
}

const handleVerifyCode = async () => {
  loading.value = true
  error.value = ''
  successMessage.value = ''

  try {
    if (mfaMode.value === 'recovery') {
      await authStore.verifyRecoveryCode(mfaChallenge.value.token, recoveryCode.value)
    } else {
      await authStore.verifyLoginCode(mfaChallenge.value.token, code.value)
    }
    finishLogin()
  } catch (err) {
    error.value = resolveLoginErrorMessage(err)
    if (shouldReturnToCredentials(err)) {
      returnToCredentials()
      error.value = resolveLoginErrorMessage(err)
    }
  } finally {
    loading.value = false
  }
}

const handleResendCode = async () => {
  resending.value = true
  error.value = ''
  successMessage.value = ''

  try {
    const response = await authStore.resendLoginCode(mfaChallenge.value.token)
    if (response?.data?.mfa_token) {
      applyMfaChallenge(response.data)
    } else {
      code.value = ''
      successMessage.value = 'Verification code sent.'
    }
  } catch (err) {
    error.value = resolveLoginErrorMessage(err)
    if (shouldReturnToCredentials(err)) {
      returnToCredentials()
      error.value = resolveLoginErrorMessage(err)
    }
  } finally {
    resending.value = false
  }
}
</script>
