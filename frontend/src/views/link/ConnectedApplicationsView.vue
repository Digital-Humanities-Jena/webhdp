<template>
  <main class="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
    <header class="flex flex-wrap items-start justify-between gap-4"><div><p class="text-xs font-semibold uppercase tracking-wider text-indigo-600">WebHDP-Link</p><h1 class="mt-2 text-2xl font-semibold text-gray-900">Connected applications</h1><p class="mt-3 max-w-2xl text-sm text-gray-600">Review which applications can use WebHDP on your behalf. Each connection has its own permissions and expiry.</p></div><button class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50" :disabled="loading || Boolean(revoking)" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button></header>
    <div v-if="error" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">{{ error }}</div>
    <div v-if="notice" class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{{ notice }}</div>
    <p v-if="!loading && !grants.length" class="rounded-xl border border-gray-200 bg-white p-8 text-sm text-gray-600">You have no connected applications. Connect from an application that supports WebHDP-Link.</p>
    <article v-for="grant in grants" :key="grant.id" class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-4"><div><h2 class="font-semibold text-gray-900">{{ grant.client_name || grant.client?.name || grant.client_id }}</h2><p class="mt-1 text-xs text-gray-500">{{ grant.service ? 'Server integration' : 'Browser connection' }} · {{ grant.client_id }}</p></div><span :class="['rounded-full px-2 py-1 text-xs font-medium', status(grant) === 'Active' ? 'bg-emerald-50 text-emerald-800' : 'bg-gray-100 text-gray-600']">{{ status(grant) }}</span></div>
      <ul class="mt-4 space-y-1 text-sm text-gray-700"><li v-for="scope in grant.scope.split(/\s+/).filter(Boolean)" :key="scope">{{ linkScopeLabels[scope] || scope }}</li></ul>
      <div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4"><p class="text-xs text-gray-500">Expires {{ formatDate(grant.expires_at) }}</p><button v-if="status(grant) === 'Active'" :disabled="Boolean(revoking)" class="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600 disabled:opacity-50" @click="revoke(grant)">{{ revoking === grant.id ? 'Disconnecting…' : 'Disconnect application' }}</button></div>
    </article>
    <p v-if="grants.length" class="text-xs text-gray-500">Disconnecting prevents further requests with this connection. Review any processing jobs separately; disconnecting does not delete their files.</p>
  </main>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import linkService from '@/services/webhdpLink.service'
import { linkErrorMessage, linkScopeLabels } from '@/utils/webhdpLink'
const loading = ref(false), revoking = ref(''), error = ref(''), notice = ref(''), grants = ref([])
const formatDate = (value) => new Date(value).toLocaleString()
const status = (grant) => grant.revoked ? 'Disconnected' : new Date(grant.expires_at).getTime() <= Date.now() ? 'Expired' : 'Active'
async function load() {
  loading.value = true
  error.value = ''
  try { grants.value = (await linkService.listGrants()).grants }
  catch (err) { error.value = linkErrorMessage(err) }
  finally { loading.value = false }
}
async function revoke(grant) {
  if (revoking.value) return
  revoking.value = grant.id
  notice.value = ''
  error.value = ''
  try {
    await linkService.revokeGrant(grant.id)
    await load()
    notice.value = 'Application disconnected. It will need your permission to connect again.'
  } catch (err) { error.value = linkErrorMessage(err) }
  finally { revoking.value = '' }
}
onMounted(load)
</script>
