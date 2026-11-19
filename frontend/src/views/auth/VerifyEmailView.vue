<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 px-4 py-12">
    <div class="max-w-md w-full space-y-6">
      <header class="text-center">
        <h1 ref="pageHeading" tabindex="-1" class="text-3xl font-bold text-gray-900">
          {{ verified ? 'Email verified' : 'Verify your email' }}
        </h1>
        <p v-if="verified" role="status" class="mt-2 text-sm text-green-800">
          Your account is ready. Sign in to continue.
        </p>
        <p v-else-if="token" class="mt-2 text-sm text-gray-600">
          Choose a password to confirm your email and activate your account.
        </p>
      </header>

      <div v-if="error" role="alert" class="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
        {{ error }}
      </div>

      <form v-if="token && !verified" class="space-y-4" :aria-busy="verifying" @submit.prevent="confirmEmail">
        <fieldset :disabled="verifying" class="space-y-4">
          <legend class="sr-only">New account password</legend>
          <div>
            <label for="password" class="block text-sm font-medium text-gray-900">Create password</label>
            <input id="password" v-model="password" type="password" autocomplete="new-password" required
              minlength="8" maxlength="128" aria-describedby="password-hint"
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:ring-indigo-500" />
            <p id="password-hint" class="mt-1 text-xs text-gray-600">Use at least eight characters.</p>
          </div>
          <div>
            <label for="confirm-password" class="block text-sm font-medium text-gray-900">Confirm password</label>
            <input id="confirm-password" ref="confirmationField" v-model="confirmation" type="password" autocomplete="new-password"
              required maxlength="128" :aria-invalid="mismatch || undefined" :aria-describedby="mismatch ? 'password-match-error' : undefined"
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:ring-indigo-500" />
            <p v-if="mismatch" id="password-match-error" class="mt-1 text-sm text-red-800">Passwords do not match.</p>
          </div>
        </fieldset>
        <button type="submit" :disabled="verifying" class="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {{ verifying ? 'Verifying…' : 'Verify email and create account' }}
        </button>
      </form>

      <div class="flex flex-wrap items-center justify-center gap-4 text-sm">
        <router-link :to="loginTo" class="font-medium text-indigo-700 underline">Sign in to WebHDP</router-link>
        <router-link v-if="!verified" :to="{ path: '/register', query: { resend: '1' } }" class="font-medium text-indigo-700 underline">
          Request a new link
        </router-link>
      </div>
      <p v-if="verified && !fromInvitation" class="text-center text-sm text-gray-600">
        Joining an institution? Return to the invitation tab and sign in there, or reopen the invitation email.
      </p>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import authService from '@/services/auth.service'
import {
  getEmailActionToken, identityActionError, institutionInvitationPath, invitationStorageKey,
  readEmailActionToken, setEmailActionToken, verificationStorageKey,
} from '@/utils/emailAction'

const route = useRoute()
const router = useRouter()
const pageHeading = ref(null)
const confirmationField = ref(null)
const password = ref('')
const confirmation = ref('')
const verifying = ref(false)
const verified = ref(false)
const mismatch = ref(false)
const error = ref('')
const token = ref('')
const fromInvitation = Boolean(getEmailActionToken(invitationStorageKey))
const loginTo = fromInvitation ? { path: '/login', query: { redirect: institutionInvitationPath } } : '/login'
let linkVersion = 0

function loadLink() {
  const incoming = readEmailActionToken(route.hash)
  if (route.hash || route.params.token) {
    linkVersion++
    verifying.value = false
    verified.value = false
    error.value = ''
    password.value = ''
    confirmation.value = ''
    setEmailActionToken(verificationStorageKey, incoming)
  }
  token.value = incoming || (!route.hash && !route.params.token ? getEmailActionToken(verificationStorageKey) : '')
  if (route.hash || route.params.token) router.replace('/verify-email')
  if (!token.value) error.value = 'This link cannot verify your account. Request a new verification email.'
}

watch([password, confirmation], () => { mismatch.value = false })

async function confirmEmail() {
  if (verifying.value || !token.value) return
  error.value = ''
  if (password.value !== confirmation.value) {
    mismatch.value = true
    await nextTick()
    confirmationField.value?.focus()
    return
  }
  const version = linkVersion
  verifying.value = true
  try {
    await authService.verifyEmail(token.value, password.value)
    if (version !== linkVersion) return
    verified.value = true
    setEmailActionToken(verificationStorageKey, '')
    token.value = ''
    await nextTick()
    pageHeading.value?.focus()
  } catch (err) {
    if (version !== linkVersion) return
    if (err?.error?.code === 'INVALID_EMAIL_VERIFICATION_LINK') {
      setEmailActionToken(verificationStorageKey, '')
      token.value = ''
    }
    error.value = identityActionError(err, 'WebHDP could not verify your email. Try again shortly.')
  } finally {
    if (version === linkVersion) {
      password.value = ''
      confirmation.value = ''
      verifying.value = false
    }
  }
}

onMounted(loadLink)
watch([() => route.hash, () => route.params.token], ([hash, legacyToken]) => {
  if (hash || legacyToken) loadLink()
})
</script>
