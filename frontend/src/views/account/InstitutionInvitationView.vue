<template>
  <main class="min-h-screen bg-gray-50 px-4 py-12 sm:grid sm:place-items-center">
    <section class="mx-auto max-w-lg space-y-5 rounded-xl border border-gray-200 bg-white p-6 sm:p-8" aria-labelledby="invite-heading">
      <h1 id="invite-heading" ref="heading" tabindex="-1" class="text-2xl font-bold text-gray-950">Institution invitation</h1>

      <template v-if="accepted">
        <p role="status" class="rounded-md bg-green-50 p-4 text-sm text-green-950">
          You joined <strong>{{ accepted.institution.name }}</strong> as {{ accepted.membership.role }}.
        </p>
        <div class="flex flex-wrap items-center gap-4 text-sm">
          <router-link :to="{ path: '/account/institutions', query: { workspace: String(accepted.institution.id) } }"
            class="font-medium text-indigo-700 underline">Open institution workspace</router-link>
          <router-link to="/onboarding" class="font-medium text-indigo-700 underline">Getting started</router-link>
        </div>
      </template>

      <template v-else-if="token && !authStore.isAuthenticated">
        <p class="text-sm text-gray-700">Sign in with the email address that received the invitation. If you’re new to WebHDP, create and verify an account with that address.</p>
        <div class="flex flex-wrap items-center gap-4 text-sm">
          <router-link :to="loginTo" class="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700">Sign in</router-link>
          <router-link to="/register" class="font-medium text-indigo-700 underline">Create an account</router-link>
        </div>
      </template>

      <template v-else-if="preview">
        <p v-if="preview.current_role" class="text-sm text-gray-700">You already have {{ preview.current_role }} access to <strong>{{ preview.institution.name }}</strong>.</p>
        <p v-else class="text-sm text-gray-700">Join <strong>{{ preview.institution.name }}</strong> as <strong>{{ preview.role }}</strong>.</p>
        <button type="button" :disabled="loading" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50" @click="accept">
          {{ loading ? 'Joining…' : 'Accept invitation' }}
        </button>
      </template>

      <p v-else-if="loading" role="status" class="text-sm text-gray-700">Checking your invitation…</p>
      <p v-else-if="!error" class="text-sm text-gray-700">Open the full link from your institution invitation email.</p>

      <div v-if="error" class="space-y-3">
        <p role="alert" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">{{ error }}</p>
        <button v-if="wrongAccount" type="button" :disabled="loading" class="text-sm font-medium text-indigo-700 underline" @click="switchAccount">
          Sign in with another account
        </button>
        <router-link v-else-if="passwordChangeRequired" to="/account/configuration" class="text-sm font-medium text-indigo-700 underline">
          Update password in account settings
        </router-link>
        <button v-else-if="token && !preview" type="button" :disabled="loading" class="text-sm font-medium text-indigo-700 underline" @click="loadPreview">
          Try again
        </button>
      </div>
    </section>
  </main>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import authService from '@/services/auth.service'
import institutionService from '@/services/institution.service'
import {
  getEmailActionToken, identityActionError, institutionInvitationPath, invitationStorageKey,
  readEmailActionToken, setEmailActionToken,
} from '@/utils/emailAction'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const heading = ref(null)
const token = ref('')
const preview = ref(null)
const accepted = ref(null)
const loading = ref(false)
const error = ref('')
const wrongAccount = ref(false)
const passwordChangeRequired = ref(false)
const loginTo = { path: '/login', query: { redirect: institutionInvitationPath } }
let linkVersion = 0

function handleError(err) {
  const code = err?.error?.code
  wrongAccount.value = code === 'INVITATION_EMAIL_MISMATCH'
  passwordChangeRequired.value = code === 'PASSWORD_CHANGE_REQUIRED'
  if (code === 'INVITATION_INVALID') {
    token.value = ''
    preview.value = null
    setEmailActionToken(invitationStorageKey, '')
    error.value = 'This invitation is unavailable. Ask the institution manager to send a new one.'
    return
  }
  error.value = identityActionError(err, 'Could not check the invitation. Try again shortly.')
}

async function loadPreview() {
  if (loading.value || !token.value || !authStore.isAuthenticated) return
  const version = linkVersion
  loading.value = true
  error.value = ''
  wrongAccount.value = false
  passwordChangeRequired.value = false
  try {
    const response = await institutionService.previewInvitation(token.value)
    if (version === linkVersion) preview.value = response.data
  } catch (err) {
    if (version === linkVersion) handleError(err)
  } finally {
    if (version === linkVersion) loading.value = false
  }
}

async function accept() {
  if (loading.value || !token.value) return
  const version = linkVersion
  loading.value = true
  error.value = ''
  try {
    const response = await institutionService.acceptInvitation(token.value)
    if (version !== linkVersion) return
    accepted.value = response.data
    token.value = ''
    setEmailActionToken(invitationStorageKey, '')
    await nextTick()
    heading.value?.focus()
  } catch (err) {
    if (version === linkVersion) handleError(err)
  } finally {
    if (version === linkVersion) loading.value = false
  }
}

async function switchAccount() {
  loading.value = true
  try {
    await authService.logout()
  } catch {
    // Clear local sign-in state even if the old session has already expired.
  } finally {
    authStore.logout()
    router.push(loginTo)
    loading.value = false
  }
}

function loadInvitationLink() {
  const incoming = readEmailActionToken(route.hash)
  if (route.hash) {
    linkVersion++
    loading.value = false
    setEmailActionToken(invitationStorageKey, incoming)
    preview.value = null
    accepted.value = null
    error.value = ''
    wrongAccount.value = false
    passwordChangeRequired.value = false
  }
  token.value = incoming || (!route.hash ? getEmailActionToken(invitationStorageKey) : '')
  if (route.hash) router.replace(institutionInvitationPath)
  loadPreview()
}

onMounted(loadInvitationLink)
watch(() => route.hash, (hash) => {
  if (hash) loadInvitationLink()
})
</script>
