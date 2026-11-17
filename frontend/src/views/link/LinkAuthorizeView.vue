<template>
  <main class="mx-auto max-w-2xl px-4 py-10 sm:px-6">
    <div class="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
      <p class="text-sm font-semibold uppercase tracking-wider text-indigo-600">WebHDP-Link</p>
      <h1 class="mt-3 text-2xl font-semibold text-gray-900">Connect an application</h1>
      <p v-if="loading" class="mt-5 text-gray-600" role="status">Checking this connection request…</p>
      <div v-if="error" class="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">{{ error }}</div>
      <a v-if="embedded" :href="directUrl" target="_top" rel="noopener noreferrer" class="mt-5 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white">Open WebHDP directly</a>
      <template v-if="requestInfo && !loading">
        <p class="mt-5 text-gray-700"><strong>{{ requestInfo.client.name }}</strong> would like to use WebHDP on your behalf.</p>
        <dl class="mt-5 space-y-3 rounded-lg bg-gray-50 p-4 text-sm">
          <div><dt class="font-medium text-gray-600">Signed in as</dt><dd class="mt-1 text-gray-900">{{ authStore.user?.email }}</dd></div>
          <div><dt class="font-medium text-gray-600">Application address</dt><dd class="mt-1 break-all font-mono text-gray-900">{{ applicationOrigin }}</dd></div>
          <div><dt class="font-medium text-gray-600">Access duration</dt><dd class="mt-1 text-gray-900">{{ duration }} minutes</dd></div>
        </dl>
        <h2 class="mt-6 font-semibold text-gray-900">Requested permissions</h2>
        <ul class="mt-3 space-y-2 text-sm text-gray-700">
          <li v-for="scope in scopes" :key="scope" class="flex gap-2"><span class="text-indigo-600" aria-hidden="true">✓</span><span>{{ linkScopeLabels[scope] || scope }}</span></li>
        </ul>
        <h2 class="mt-6 font-semibold text-gray-900">Available pipelines</h2>
        <ul class="mt-3 space-y-2">
          <li v-for="pipeline in requestInfo.pipelines" :key="pipeline.id" class="rounded-lg border border-gray-200 p-3 text-sm">
            <p class="font-medium text-gray-900">{{ pipeline.name }} <span class="ml-1 font-normal text-gray-500">{{ pipeline.pipeline_version }}</span></p>
            <p v-if="pipeline.description" class="mt-1 text-gray-600">{{ pipeline.description }}</p>
          </li>
        </ul>
        <p class="mt-5 text-sm text-gray-600">Approving lets this application use the listed pipelines within its configured limits. Processing jobs may use shared computing resources.</p>
        <p class="mt-3 text-sm text-gray-600">You can withdraw access at any time from Connected Apps in WebHDP.</p>
        <div class="mt-7 flex flex-wrap gap-3">
          <button type="button" :disabled="submitting" class="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50" @click="decide(true)">{{ submitting ? 'Returning to application…' : 'Allow connection' }}</button>
          <button type="button" :disabled="submitting" class="rounded-lg border border-gray-300 px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50" @click="decide(false)">Deny</button>
        </div>
      </template>
      <router-link v-if="!loading && !requestInfo && !embedded" to="/dashboard" class="mt-5 inline-block text-sm font-medium text-indigo-600">Return to WebHDP</router-link>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import linkService from '@/services/webhdpLink.service'
import { authorizationParameters, isEmbeddedLinkWindow, linkErrorMessage, linkScopeLabels, navigateLinkCallback } from '@/utils/webhdpLink'

const route = useRoute()
const authStore = useAuthStore()
const parameters = authorizationParameters(route.query)
const loading = ref(true)
const embedded = ref(false)
const directUrl = window.location.href
const submitting = ref(false)
const error = ref('')
const requestInfo = ref(null)
const scopes = computed(() => String(requestInfo.value?.scope || '').split(/\s+/).filter(Boolean))
const duration = computed(() => Math.ceil(Number(requestInfo.value?.expires_in || 3600) / 60))
const applicationOrigin = computed(() => {
  try { return new URL(requestInfo.value?.redirect_uri).origin } catch { return '' }
})

onMounted(async () => {
  if (isEmbeddedLinkWindow()) {
    embedded.value = true
    error.value = 'For your security, application connections cannot be approved inside another page. Open WebHDP directly to review this request.'
    loading.value = false
    return
  }
  try { requestInfo.value = await linkService.authorizationRequest(parameters) }
  catch (err) { error.value = linkErrorMessage(err) }
  finally { loading.value = false }
})

async function decide(approve) {
  if (submitting.value || !requestInfo.value) return
  submitting.value = true
  error.value = ''
  try {
    const result = await linkService.authorize({ ...parameters, approve })
    navigateLinkCallback(result.redirect_uri, requestInfo.value.redirect_uri)
  } catch (err) {
    error.value = linkErrorMessage(err)
    submitting.value = false
  }
}
</script>
