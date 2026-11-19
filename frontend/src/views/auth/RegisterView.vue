<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 px-4 py-12">
    <div class="max-w-md w-full space-y-6">
      <header class="text-center">
        <h1 ref="pageHeading" tabindex="-1" class="text-3xl font-bold text-gray-900">
          {{ sent ? 'Check your inbox' : resendMode ? 'Request a new verification link' : 'Create your WebHDP account' }}
        </h1>
        <p v-if="!sent" class="mt-2 text-sm text-gray-600">
          Verify your email first. You’ll choose a password after opening the link.
        </p>
      </header>

      <div v-if="error" role="alert" class="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
        {{ error }}
      </div>

      <div v-if="sent" class="space-y-4">
        <p role="status" class="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">
          If verification is available for <strong class="break-all">{{ email }}</strong>, you’ll receive a WebHDP email.
          Check spam or junk if it hasn’t arrived.
        </p>
        <p v-if="fromInvitation" class="text-sm text-gray-600">After verifying your email, return to this tab and sign in to continue the invitation.</p>
        <div class="flex flex-wrap items-center justify-center gap-4 text-sm">
          <button type="button" :disabled="loading" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="sendLink(true)">
            {{ loading ? 'Requesting…' : 'Resend verification email' }}
          </button>
          <button type="button" :disabled="loading" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="useAnotherAddress">
            Use another email
          </button>
        </div>
      </div>

      <form v-else class="space-y-4" :aria-busy="loading" @submit.prevent="sendLink(resendMode)">
        <div>
          <label for="email" class="block text-sm font-medium text-gray-900">Email address</label>
          <input id="email" ref="emailInput" v-model.trim="email" type="text" inputmode="email" name="email" required maxlength="254"
            autocomplete="email" autocapitalize="none" :spellcheck="false" :disabled="loading"
            class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
          <p v-if="fromInvitation" class="mt-2 text-sm text-gray-600">Use the address that received the institution invitation.</p>
        </div>
        <button type="submit" :disabled="loading"
          class="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50">
          {{ loading ? 'Requesting…' : resendMode ? 'Resend verification email' : 'Send verification email' }}
        </button>
      </form>

      <div class="flex flex-wrap items-center justify-center gap-4 text-sm">
        <router-link :to="loginTo" class="font-medium text-indigo-700 underline">Sign in</router-link>
        <router-link v-if="!sent && !resendMode" :to="{ path: '/register', query: { resend: '1' } }"
          class="font-medium text-indigo-700 underline">Resend verification</router-link>
        <router-link v-if="fromInvitation" :to="institutionInvitationPath" class="font-medium text-indigo-700 underline">Back to invitation</router-link>
      </div>

      <LegalLinks />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import authService from '@/services/auth.service'
import LegalLinks from '@/components/legal/LegalLinks.vue'
import { getEmailActionToken, identityActionError, institutionInvitationPath, invitationStorageKey } from '@/utils/emailAction'

const route = useRoute()
const authStore = useAuthStore()
const pageHeading = ref(null)
const emailInput = ref(null)
const email = ref('')
const loading = ref(false)
const sent = ref(false)
const error = ref('')
const resendMode = computed(() => route.query.resend === '1')
const fromInvitation = Boolean(getEmailActionToken(invitationStorageKey))
const loginTo = fromInvitation ? { path: '/login', query: { redirect: institutionInvitationPath } } : '/login'

async function sendLink(resend) {
  if (loading.value || !email.value) return
  loading.value = true
  error.value = ''
  try {
    if (resend) await authService.resendVerification(email.value)
    else await authStore.register(email.value)
    sent.value = true
    await nextTick()
    pageHeading.value?.focus()
  } catch (err) {
    error.value = identityActionError(err, 'Could not request a verification email. Try again shortly.')
  } finally {
    loading.value = false
  }
}

async function useAnotherAddress() {
  email.value = ''
  sent.value = false
  error.value = ''
  await nextTick()
  emailInput.value?.focus()
}
</script>
