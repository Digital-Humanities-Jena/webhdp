<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-5xl space-y-5 px-4 py-8 sm:px-6 lg:px-8">
      <header>
        <router-link to="/onboarding" class="text-sm font-medium text-indigo-700 hover:underline">Getting started</router-link>
        <h1 class="mt-2 text-3xl font-semibold text-gray-900">Set up your account</h1>
        <p class="mt-2 text-sm text-gray-700">Choose the optional steps you need. Return here from Account Configuration to check your progress.</p>
      </header>

      <section class="setup-section" aria-labelledby="setup-zenodo-heading">
        <h2 id="setup-zenodo-heading" class="setup-heading">Connect Zenodo</h2>
        <p class="mt-2 text-sm text-gray-700">
          Add a key from the matching Zenodo site, validate it, then set it active. Validation creates a temporary draft and checks that it can be removed.
        </p>
        <router-link to="/docs/zenodo-api-keys" class="setup-link mt-2 inline-block">How to create a Zenodo API key</router-link>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <article v-for="step in zenodoSteps" :key="step.environment" class="rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="text-sm font-semibold text-gray-900">{{ step.title }}</h3>
              <span class="setup-status" :class="step.ready ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-200 text-gray-800'">
                {{ step.status }}
              </span>
            </div>
            <p class="mt-2 text-sm text-gray-700">{{ step.description }}</p>
            <router-link :to="step.to" class="setup-link mt-3 inline-block">{{ step.action }}</router-link>
          </article>
        </div>
        <div v-if="credentialState === 'unavailable'" class="mt-3 flex flex-wrap items-center gap-2 text-sm text-gray-700">
          <span role="status">Could not check your saved Zenodo keys.</span>
          <button type="button" class="setup-link" @click="loadStatus">Refresh setup status</button>
        </div>
      </section>

      <section class="setup-section" aria-labelledby="setup-workspace-heading">
        <h2 id="setup-workspace-heading" class="setup-heading">Find or request an institution workspace</h2>
        <p class="mt-2 text-sm text-gray-700">
          Workspaces let an institution manage shared uploads. A workspace manager can email you an invitation. Open it while signed in with the address that received it.
        </p>

        <div v-if="institutions.length" class="mt-4">
          <h3 class="text-sm font-semibold text-gray-900">Your memberships</h3>
          <ul class="mt-2 divide-y divide-gray-200 rounded-lg border border-gray-200">
            <li v-for="institution in institutions" :key="institution.id" class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
              <router-link :to="workspaceLink(institution.id)" class="setup-link">{{ institution.display_name || institution.name }}</router-link>
              <span class="capitalize text-gray-700">{{ institution.role }}</span>
            </li>
          </ul>
        </div>
        <p v-else class="mt-3 text-sm text-gray-700">You have no workspace memberships yet.</p>

        <form class="mt-5" @submit.prevent="findWorkspaces">
          <label for="setup-workspace-search" class="block text-sm font-medium text-gray-900">Search visible workspaces</label>
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <input id="setup-workspace-search" v-model="workspaceQuery" type="search" maxlength="255"
              class="w-full min-w-0 rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500 sm:max-w-xs" />
            <button type="submit" :disabled="!workspaceQuery.trim() || searchState === 'loading'"
              class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              Search
            </button>
          </div>
        </form>
        <p v-if="searchState === 'loading'" class="mt-3 text-sm text-gray-700" role="status">Searching for workspaces…</p>
        <p v-else-if="searchState === 'unavailable'" class="mt-3 text-sm text-rose-700" role="status">Workspace search is unavailable. Try again.</p>
        <p v-else-if="searchState === 'complete' && !matches.length" class="mt-3 text-sm text-gray-700" role="status">
          No visible workspaces match this search. Your institution may have a private workspace. Ask your institution before requesting a new one.
        </p>
        <ul v-else-if="matches.length" class="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200" aria-label="Workspace search results">
          <li v-for="institution in matches" :key="institution.id" class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <span class="font-medium text-gray-900">{{ institution.display_name || institution.name }}</span>
            <router-link v-if="canOpenWorkspace(institution)" :to="workspaceLink(institution.id)" class="setup-link">Open workspace</router-link>
            <span v-else class="text-gray-700">Ask the workspace manager for an invitation</span>
          </li>
        </ul>

        <div class="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2">
          <router-link v-if="hasInvitation" :to="institutionInvitationPath" class="setup-link">Continue an invitation</router-link>
          <router-link v-if="isAdmin" to="/account/institutions#create-institution" class="setup-link">Create a workspace</router-link>
          <router-link to="/account/institutions#workspace-requests-title" class="setup-link">
            {{ isAdmin ? 'Review workspace requests' : pendingRequests ? 'Check your workspace requests' : 'Request a new workspace' }}
          </router-link>
          <span v-if="requestState === 'loading'" class="text-sm text-gray-700" role="status">Checking workspace requests…</span>
          <span v-else-if="requestState === 'unavailable'" class="flex flex-wrap items-center gap-2 text-sm text-gray-700">
            <span role="status">Request status unavailable</span>
            <button v-if="credentialState !== 'unavailable'" type="button" class="setup-link" @click="loadStatus">Refresh setup status</button>
          </span>
          <span v-else-if="pendingRequests" class="setup-status bg-amber-100 text-amber-900">
            {{ pendingRequests }} awaiting approval
          </span>
        </div>
        <p v-if="!isAdmin" class="mt-2 text-sm text-gray-700">A site administrator reviews new workspace requests.</p>
      </section>

      <section v-if="isAdmin || manageableInstitutions.length" class="setup-section" aria-labelledby="setup-invite-heading">
        <h2 id="setup-invite-heading" class="setup-heading">Invite colleagues</h2>
        <p class="mt-2 text-sm text-gray-700">Choose a workspace you manage, then send an email invitation with the role your colleague needs.</p>
        <ul v-if="manageableInstitutions.length" class="mt-3 space-y-2">
          <li v-for="institution in manageableInstitutions" :key="institution.id">
            <router-link :to="workspaceLink(institution.id, 'members')" class="setup-link">
              Invite to {{ institution.display_name || institution.name }}
            </router-link>
          </li>
        </ul>
        <router-link v-if="isAdmin" to="/account/institutions" class="setup-link mt-3 inline-block">Manage all workspaces</router-link>
      </section>

      <section class="setup-section" aria-labelledby="setup-profile-heading">
        <h2 id="setup-profile-heading" class="setup-heading">Profile and computing access</h2>
        <div class="mt-3 grid gap-4 sm:grid-cols-2">
          <article>
            <h3 class="text-sm font-semibold text-gray-900">Profile details</h3>
            <p class="mt-1 text-sm text-gray-700">
              {{ hasFullName ? 'Your full name is saved.' : 'Add your full name and affiliation to prefill an HPC access request.' }}
            </p>
            <router-link to="/account/configuration#profile-settings" class="setup-link mt-2 inline-block">Open profile settings</router-link>
          </article>
          <article>
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-sm font-semibold text-gray-900">HPC resources</h3>
              <span class="setup-status bg-gray-200 text-gray-800">{{ hpcStatus }}</span>
            </div>
            <p class="mt-1 text-sm text-gray-700">
              {{ hpcAccess ? 'HPC access is enabled for this account.' : 'Request access to remote computing for pipelines that need it.' }}
            </p>
            <router-link to="/hpc-resources" class="setup-link mt-2 inline-block">Open HPC access</router-link>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import authService from '@/services/auth.service'
import institutionService from '@/services/institution.service'
import { getEmailActionToken, institutionInvitationPath, invitationStorageKey } from '@/utils/emailAction'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')
const institutions = computed(() => authStore.institutions || [])
const manageableInstitutions = computed(() => institutions.value.filter(item => isAdmin.value || ['manager', 'owner'].includes(item.role)))
const hasInvitation = Boolean(getEmailActionToken(invitationStorageKey))
const hasFullName = computed(() => Boolean(authStore.user?.full_name))
const hpcAccess = computed(() => Boolean(authStore.user?.hpc?.has_access))
const hpcStatus = computed(() => {
  if (hpcAccess.value) return 'Access enabled'
  const requestStatus = authStore.user?.hpc?.latest_request?.status
  if (requestStatus === 'pending') return 'Awaiting approval'
  if (requestStatus === 'rejected') return 'Not approved'
  return 'Optional'
})

const credentialState = ref('loading')
const credentials = ref({})
const requestState = ref('loading')
const pendingRequests = ref(0)
const workspaceQuery = ref('')
const searchState = ref('idle')
const matches = ref([])
let statusVersion = 0
let searchVersion = 0
const validationStatuses = {
  valid: 'Validated',
  invalid: 'Check key',
  unreachable: 'Check connection',
  warning: 'Review validation',
}

function workspaceLink(id, section) {
  return { path: '/account/institutions', query: { workspace: String(id), ...(section ? { section } : {}) } }
}

function canOpenWorkspace(institution) {
  return isAdmin.value || institutions.value.some(item => String(item.id) === String(institution.id))
}

function describeCredential(environment, title, description) {
  const active = credentials.value.active?.[environment]
  const hasKey = Boolean(active || credentials.value.credentials?.some(item => item.environment === environment))
  let status = 'No key added'
  if (credentialState.value === 'loading') status = 'Checking…'
  else if (credentialState.value === 'unavailable') status = 'Status unavailable'
  else if (active) status = validationStatuses[active.validation_status] || 'Validate active key'
  else if (hasKey) status = 'Choose an active key'
  return {
    environment, title, description, status,
    ready: credentialState.value === 'ready' && active?.validation_status === 'valid',
    action: `${hasKey || credentialState.value !== 'ready' ? 'Manage' : 'Add'} ${title} key`,
    to: {
      path: '/account/configuration',
      query: { zenodo: environment },
      hash: hasKey ? `#zenodo-${environment}` : '#zenodo-keys',
    },
  }
}

const zenodoSteps = computed(() => [
  describeCredential('sandbox', 'Sandbox', 'Use a key from Zenodo Sandbox for test drafts.'),
  describeCredential('production', 'Production', 'Use a separate key from Zenodo for real deposits.'),
])

async function loadStatus() {
  if (!authStore.user?.id) return
  const version = ++statusVersion
  credentialState.value = 'loading'
  requestState.value = 'loading'
  const [savedKeys, requests] = await Promise.allSettled([
    authService.listZenodoCredentials({ suppressGlobalError: true }),
    institutionService.listWorkspaceRequests({ status: 'pending', per_page: 1, ...(isAdmin.value ? { all: true } : {}) }),
  ])
  if (version !== statusVersion) return
  credentials.value = savedKeys.status === 'fulfilled' ? savedKeys.value.data || {} : {}
  credentialState.value = savedKeys.status === 'fulfilled' ? 'ready' : 'unavailable'
  pendingRequests.value = requests.status === 'fulfilled' ? requests.value.data?.pagination?.total || 0 : 0
  requestState.value = requests.status === 'fulfilled' ? 'ready' : 'unavailable'
}

async function findWorkspaces() {
  const query = workspaceQuery.value.trim()
  if (!query) return
  const version = ++searchVersion
  searchState.value = 'loading'
  matches.value = []
  try {
    const result = await institutionService.suggestInstitutions(query, {}, { suppressGlobalError: true })
    if (version !== searchVersion) return
    matches.value = result.data?.institutions || []
    searchState.value = 'complete'
  } catch {
    if (version === searchVersion) searchState.value = 'unavailable'
  }
}

watch(workspaceQuery, () => {
  searchVersion++
  matches.value = []
  searchState.value = 'idle'
})

watch([() => authStore.user?.id, isAdmin], () => {
  credentials.value = {}
  pendingRequests.value = 0
  workspaceQuery.value = authStore.user?.affiliation || ''
  matches.value = []
  searchState.value = 'idle'
  searchVersion++
  statusVersion++
  loadStatus()
}, { immediate: true })
</script>

<style scoped>
.setup-section {
  @apply rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6;
}

.setup-heading {
  @apply text-lg font-semibold text-gray-900;
}

.setup-link {
  @apply text-sm font-semibold text-indigo-700 underline-offset-2 hover:underline;
}

.setup-status {
  @apply rounded-full px-2.5 py-1 text-xs font-medium;
}
</style>
