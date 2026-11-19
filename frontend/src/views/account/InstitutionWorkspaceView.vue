<template>
  <div class="min-h-screen bg-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <section class="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-6 py-5 border-b border-gray-200 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-gray-900">Institution Workspaces</h1>
            <p class="text-sm text-gray-500 mt-1">Open your institution’s shared workspace or request a new one.</p>
          </div>
          <div v-if="isAdmin" id="create-institution" class="flex gap-3">
            <input
              v-model.trim="createForm.name"
              type="text"
              aria-label="New institution name"
              maxlength="255"
              placeholder="New institution name"
              class="block rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            />
            <button
              type="button"
              :disabled="creatingInstitution || !createForm.name"
              class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
              @click="createInstitution"
            >
              {{ creatingInstitution ? 'Creating...' : 'Create institution' }}
            </button>
          </div>
        </div>
        <div class="grid grid-cols-1 xl:grid-cols-4 divide-y xl:divide-y-0 xl:divide-x divide-gray-200">
          <aside class="xl:col-span-1 p-5 bg-gray-50 space-y-3">
            <div v-if="loadingInstitutions" class="text-sm text-gray-500">Loading institutions...</div>
            <div v-else-if="!institutionOptions.length" class="rounded-lg border border-dashed border-gray-300 bg-white p-4 text-sm text-gray-500">
              {{ isAdmin ? 'There are no institution workspaces yet.' : 'You have no memberships yet. Open your invitation email to join an existing workspace.' }}
            </div>
            <button
              v-for="institution in institutionOptions"
              :key="institution.id"
              type="button"
              class="w-full rounded-xl border px-4 py-3 text-left transition"
              :class="selectedInstitutionId === institution.id ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 bg-white hover:border-gray-300'"
              @click="selectInstitution(institution.id)"
            >
              <p class="text-sm font-semibold text-gray-900">{{ institution.name }}</p>
              <p class="text-xs text-gray-500 mt-1 capitalize">{{ institution.role ? `${institution.role} role` : 'Site administration' }}</p>
            </button>
          </aside>

          <div class="xl:col-span-3 p-6">
            <div v-if="loadingDetail" class="text-sm text-gray-500">Loading institution workspace...</div>
            <div v-else-if="!selectedInstitution" class="text-sm text-gray-500">Select an institution to view its workspace settings.</div>
            <div v-else class="space-y-6">
              <section class="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <article class="rounded-xl border border-gray-200 p-5">
                  <div class="flex items-center justify-between gap-4">
                    <div>
                      <h2 class="text-lg font-semibold text-gray-900">{{ selectedInstitution.name }}</h2>
                      <p class="text-sm text-gray-500 mt-1">{{ selectedInstitution.slug }}</p>
                    </div>
                    <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                      {{ selectedInstitution.member_count || 0 }} members
                    </span>
                  </div>
                  <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="md:col-span-2">
                      <label class="block text-sm font-medium text-gray-700 mb-1">Name</label>
                      <input v-model.trim="institutionForm.name" type="text" :disabled="!isAdmin" maxlength="255" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 disabled:bg-gray-50 sm:text-sm" />
                    </div>
                    <div class="md:col-span-2">
                      <label for="workspace-description" class="block text-sm font-medium text-gray-700 mb-1">Description</label>
                      <textarea id="workspace-description" v-model.trim="institutionForm.description" rows="4" maxlength="10000"
                        :disabled="!canManageInstitution" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 disabled:bg-gray-50 sm:text-sm" />
                    </div>
                    <div v-if="canManageInstitution" class="md:col-span-2">
                      <label for="workspace-visibility" class="block text-sm font-medium text-gray-700 mb-1">Directory visibility</label>
                      <select id="workspace-visibility" v-model="institutionForm.profileVisibility" aria-describedby="workspace-visibility-help"
                        class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                        <option value="private">Private</option>
                        <option value="internal">Visible to signed-in users</option>
                      </select>
                      <p id="workspace-visibility-help" class="mt-1 text-xs text-gray-600">
                        Visibility makes the institution searchable and shares its profile, including the description, with signed-in users. Joining still requires an invitation.
                      </p>
                    </div>
                  </div>
                  <div class="mt-4 flex justify-end">
                    <button
                      type="button"
                      :disabled="savingInstitution || !canManageInstitution"
                      class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
                      @click="saveInstitution"
                    >
                      {{ savingInstitution ? 'Saving...' : 'Save institution' }}
                    </button>
                  </div>
                </article>

                <article class="rounded-xl border border-gray-200 p-5">
                  <h2 class="text-lg font-semibold text-gray-900">Institution Zenodo Credentials</h2>
                  <p class="text-sm text-gray-500 mt-1">These are used by shared sessions that prefer institution-level publishing credentials.</p>
                  <div v-if="canManageInstitution" class="mt-4 space-y-4">
                    <div
                      v-for="environment in credentialEnvironments"
                      :key="environment"
                      class="rounded-lg border border-gray-200 p-4"
                    >
                      <div class="flex items-start justify-between gap-4">
                        <div>
                          <p class="text-sm font-semibold text-gray-900 capitalize">{{ environment }}</p>
                          <p class="text-xs text-gray-500 mt-1">
                            Current token:
                            <span class="font-medium text-gray-700">{{ institutionCredentialState[environment].credential?.masked_preview || 'Not configured' }}</span>
                          </p>
                          <p class="text-xs text-gray-500 mt-1">
                            Validation:
                            <span class="font-medium text-gray-700 capitalize">{{ institutionCredentialState[environment].credential?.validation_status || 'unknown' }}</span>
                          </p>
                        </div>
                        <span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="environment === 'sandbox' ? 'bg-indigo-100 text-indigo-700' : 'bg-emerald-100 text-emerald-700'">
                          {{ environment }}
                        </span>
                      </div>
                      <div class="mt-3 space-y-3">
                        <input
                          v-model.trim="institutionCredentialState[environment].token"
                          type="password"
                          :disabled="!canManageInstitution"
                          class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                        />
                        <div class="flex flex-wrap gap-2">
                          <button type="button" :disabled="!canManageInstitution || institutionCredentialState[environment].saving || !institutionCredentialState[environment].token" class="px-3 py-2 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50" @click="saveInstitutionCredential(environment)">
                            {{ institutionCredentialState[environment].saving ? 'Saving...' : 'Save token' }}
                          </button>
                          <button type="button" :disabled="!canManageInstitution || institutionCredentialState[environment].validating || !institutionCredentialState[environment].credential" class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50" @click="validateInstitutionCredential(environment)">
                            {{ institutionCredentialState[environment].validating ? 'Validating...' : 'Validate' }}
                          </button>
                          <button type="button" :disabled="!canManageInstitution || institutionCredentialState[environment].deleting || !institutionCredentialState[environment].credential" class="px-3 py-2 text-xs font-medium text-red-600 border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50" @click="deleteInstitutionCredential(environment)">
                            {{ institutionCredentialState[environment].deleting ? 'Deleting...' : 'Delete' }}
                          </button>
                        </div>
                        <ZenodoCredentialValidationReport
                          v-if="institutionCredentialState[environment].credential"
                          :credential="institutionCredentialState[environment].credential"
                        />
                      </div>
                    </div>
                  </div>
                  <div v-else class="mt-4 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
                    Institution credentials are visible to managers and owners only.
                  </div>
                </article>
              </section>

              <section class="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <article class="rounded-xl border border-gray-200 p-5">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <h2 ref="memberHeading" tabindex="-1" class="text-lg font-semibold text-gray-900">Members</h2>
                      <p class="text-sm text-gray-500 mt-1">Managers and owners can maintain shared membership here.</p>
                    </div>
                  </div>
                  <div class="mt-4 space-y-4">
                    <InstitutionInvitations v-if="canManageInstitution" :key="selectedInstitution.id"
                      :institution-id="selectedInstitution.id" :roles="assignableInstitutionRoles"
                      @changed="loadInstitutionAuditEvents(selectedInstitution.id)" />
                    <div
                      v-for="membership in selectedInstitution.memberships || []"
                      :key="membership.id"
                      class="rounded-lg border border-gray-200 p-4"
                    >
                      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div>
                          <p class="text-sm font-semibold text-gray-900">{{ memberLabel(membership) }}</p>
                          <p v-if="membership.user?.email && membership.user.email !== memberLabel(membership)" class="text-xs text-gray-500 mt-1">
                            {{ membership.user.email }}
                          </p>
                        </div>
                        <div v-if="canManageInstitution" class="flex items-center gap-2">
                          <select
                            :value="membership.role"
                            :aria-label="`Role for ${memberLabel(membership)}`"
                            :disabled="membership.role === 'owner' && !canManageOwners"
                            class="block rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                            @change="updateMembershipRole(membership, $event.target.value)"
                          >
                            <option v-for="role in (membership.role === 'owner' ? institutionRoles : assignableInstitutionRoles)" :key="role" :value="role">{{ role }}</option>
                          </select>
                          <button
                            type="button"
                            :aria-label="`Remove ${memberLabel(membership)}`"
                            :disabled="membership.role === 'owner' && !canManageOwners"
                            class="px-3 py-2 text-xs font-medium text-red-600 border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50"
                            @click="removeMembership(membership)"
                          >
                            Remove
                          </button>
                        </div>
                        <p v-else class="text-sm capitalize text-gray-600">{{ membership.role }}</p>
                      </div>
                    </div>
                  </div>
                </article>

                <article class="rounded-xl border border-gray-200 p-5">
                  <h2 class="text-lg font-semibold text-gray-900">Default Communities</h2>
                  <p class="text-sm text-gray-500 mt-1">These can be appended automatically to institution-backed session metadata.</p>
                  <div class="mt-4 space-y-4">
                    <div v-if="selectedInstitution?.community_policy" class="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <p class="text-xs font-semibold uppercase tracking-wide text-gray-500">Effective policy</p>
                      <p class="mt-2 text-sm text-gray-700">
                        Primary submission:
                        <span class="font-medium text-gray-900">{{ selectedInstitution.community_policy.primary_submission_community || 'None' }}</span>
                      </p>
                      <p class="mt-1 text-sm text-gray-700">
                        Moderation defaults:
                        <span class="font-medium text-gray-900">{{ selectedInstitution.community_policy.moderation_default_communities?.join(', ') || 'None' }}</span>
                      </p>
                      <p class="mt-1 text-sm text-gray-700">
                        Default append order:
                        <span class="font-medium text-gray-900">{{ selectedInstitution.community_policy.default_communities?.join(', ') || 'None' }}</span>
                      </p>
                    </div>
                    <div v-if="canManageInstitution" class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_110px_110px_130px_120px_auto] gap-3">
                      <input v-model.trim="communityForm.identifier" type="text" placeholder="community-id" class="block rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
                      <label class="flex items-center gap-2 text-xs text-gray-600"><input v-model="communityForm.enabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /> Enabled</label>
                      <label class="flex items-center gap-2 text-xs text-gray-600"><input v-model="communityForm.is_primary_submission" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /> Primary</label>
                      <label class="flex items-center gap-2 text-xs text-gray-600"><input v-model="communityForm.is_moderation_default" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /> Moderation</label>
                      <input v-model.number="communityForm.sort_order" type="number" placeholder="Sort order" class="block rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
                      <button type="button" :disabled="savingCommunity || !communityForm.identifier" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50" @click="addCommunity">
                        {{ savingCommunity ? 'Saving...' : 'Add community' }}
                      </button>
                    </div>
                    <div
                      v-for="community in selectedInstitution.communities || []"
                      :key="community.id"
                      class="rounded-lg border border-gray-200 p-4"
                    >
                      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div>
                          <div class="flex flex-wrap items-center gap-2">
                            <p class="text-sm font-semibold text-gray-900">{{ community.identifier }}</p>
                            <span v-if="community.is_primary_submission" class="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700">Primary</span>
                            <span v-if="community.is_moderation_default" class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">Moderation default</span>
                          </div>
                          <p class="text-xs text-gray-500 mt-1">Order {{ community.sort_order }} · {{ community.enabled ? 'enabled' : 'disabled' }}</p>
                        </div>
                        <div class="flex flex-wrap items-center gap-2">
                          <input
                            :value="community.sort_order"
                            :disabled="!canManageInstitution"
                            type="number"
                            class="w-24 rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                            @change="updateCommunitySortOrder(community, $event.target.value)"
                          />
                          <button type="button" :disabled="!canManageInstitution" class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50" @click="togglePrimaryCommunity(community)">
                            {{ community.is_primary_submission ? 'Unset primary' : 'Set primary' }}
                          </button>
                          <button type="button" :disabled="!canManageInstitution" class="px-3 py-2 text-xs font-medium text-amber-700 border border-amber-200 rounded-md hover:bg-amber-50 disabled:opacity-50" @click="toggleModerationDefault(community)">
                            {{ community.is_moderation_default ? 'Clear moderation' : 'Set moderation' }}
                          </button>
                          <button type="button" :disabled="!canManageInstitution" class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50" @click="toggleCommunity(community)">
                            {{ community.enabled ? 'Disable' : 'Enable' }}
                          </button>
                          <button type="button" :disabled="!canManageInstitution" class="px-3 py-2 text-xs font-medium text-red-600 border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50" @click="removeCommunity(community)">
                            Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </section>

              <section>
                <article class="rounded-xl border border-gray-200 p-5">
                  <div class="flex items-start justify-between gap-4">
                    <div>
                      <h2 class="text-lg font-semibold text-gray-900">Governance Audit</h2>
                      <p class="text-sm text-gray-500 mt-1">Recent credential, membership, community, and workspace policy events for this institution.</p>
                    </div>
                    <button
                      v-if="canManageInstitution"
                      type="button"
                      class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                      :disabled="loadingAudit || !selectedInstitution"
                      @click="loadInstitutionAuditEvents(selectedInstitution?.id)"
                    >
                      {{ loadingAudit ? 'Refreshing...' : 'Refresh audit' }}
                    </button>
                  </div>
                  <div v-if="!canManageInstitution" class="mt-4 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
                    Audit history is visible to managers and owners only.
                  </div>
                  <div v-else class="mt-4 space-y-3">
                    <div v-if="loadingAudit" class="text-sm text-gray-500">Loading audit events...</div>
                    <div v-else-if="!auditEvents.length" class="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
                      No audit events recorded yet.
                    </div>
                    <div
                      v-for="event in auditEvents"
                      :key="event.id"
                      class="rounded-lg border border-gray-200 p-4"
                    >
                      <div class="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                        <div>
                          <p class="text-sm font-semibold text-gray-900">{{ event.event_type }}</p>
                          <p class="text-xs text-gray-500 mt-1">
                            {{ event.actor?.email || 'System' }} · {{ event.entity_type }}{{ event.entity_id ? ` #${event.entity_id}` : '' }}
                          </p>
                        </div>
                        <p class="text-xs text-gray-500">{{ formatTimestamp(event.created_at) }}</p>
                      </div>
                    </div>
                    <p v-if="auditPagination.total" class="text-xs text-gray-500">
                      Showing {{ auditEvents.length }} of {{ auditPagination.total }} events.
                    </p>
                  </div>
                </article>
              </section>
            </div>
          </div>
        </div>
      </section>
      <InstitutionWorkspaceRequests :key="isAdmin" :admin="isAdmin" @approved="openApprovedWorkspace" />
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ZenodoCredentialValidationReport from '@/components/account/ZenodoCredentialValidationReport.vue'
import InstitutionInvitations from '@/components/account/InstitutionInvitations.vue'
import InstitutionWorkspaceRequests from '@/components/account/InstitutionWorkspaceRequests.vue'
import institutionService from '@/services/institution.service'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const authStore = useAuthStore()
const toast = useToast()
const route = useRoute()
const router = useRouter()

const credentialEnvironments = ['sandbox', 'production']
const institutionRoles = ['reader', 'curator', 'manager', 'owner']

const loadingInstitutions = ref(false)
const loadingDetail = ref(false)
const creatingInstitution = ref(false)
const savingInstitution = ref(false)
const savingCommunity = ref(false)
const loadingAudit = ref(false)
const selectedInstitutionId = ref(null)
const selectedInstitution = ref(null)
const memberHeading = ref(null)
const adminInstitutions = ref([])
const auditEvents = ref([])
const auditPagination = reactive({ page: 1, per_page: 10, total: 0, pages: 1 })

const createForm = reactive({ name: '' })
const institutionForm = reactive({ name: '', description: '', profileVisibility: 'private' })
const communityForm = reactive({ identifier: '', enabled: true, is_primary_submission: false, is_moderation_default: false, sort_order: 0 })
const institutionCredentialState = reactive({
  sandbox: { credential: null, token: '', saving: false, validating: false, deleting: false },
  production: { credential: null, token: '', saving: false, validating: false, deleting: false },
})

const isAdmin = computed(() => authStore.user?.role === 'admin')
const institutionOptions = computed(() => isAdmin.value ? adminInstitutions.value : authStore.institutions || [])
const currentInstitutionRole = computed(() => {
  const institution = institutionOptions.value.find((item) => item.id === selectedInstitutionId.value)
  return institution?.role || null
})
const canManageInstitution = computed(() => isAdmin.value || ['manager', 'owner'].includes(currentInstitutionRole.value))
const canManageOwners = computed(() => isAdmin.value || currentInstitutionRole.value === 'owner')
const assignableInstitutionRoles = computed(() => canManageOwners.value ? institutionRoles : institutionRoles.filter(role => role !== 'owner'))
const formatTimestamp = (value) => value ? new Date(value).toLocaleString() : 'Unknown'
const memberLabel = (membership) => membership.user?.display_name || membership.user?.full_name || membership.user?.email
  || (canManageInstitution.value ? `Member #${membership.user_id}` : 'Member')

const resetInstitutionForm = (institution) => {
  institutionForm.name = institution?.name || ''
  institutionForm.description = institution?.description || ''
  institutionForm.profileVisibility = institution?.profile_visibility === 'internal' ? 'internal' : 'private'
}

const resetInstitutionCredentials = () => {
  credentialEnvironments.forEach((environment) => {
    institutionCredentialState[environment].credential = selectedInstitution.value?.zenodo_credentials?.[environment] || null
    institutionCredentialState[environment].token = ''
  })
}

const refreshAuthUser = async () => {
  try {
    await authStore.fetchCurrentUser()
  } catch (error) {
    console.error('Failed to refresh current user after institution update:', error)
  }
}

const loadInstitutionDetail = async (institutionId) => {
  if (!institutionId) {
    selectedInstitution.value = null
    auditEvents.value = []
    return
  }
  loadingDetail.value = true
  try {
    const response = await institutionService.getInstitution(institutionId)
    if (institutionId !== selectedInstitutionId.value) return
    selectedInstitution.value = response.data?.institution || null
    resetInstitutionForm(selectedInstitution.value)
    resetInstitutionCredentials()
    await loadInstitutionAuditEvents(institutionId)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to load institution workspace')
  } finally {
    if (institutionId === selectedInstitutionId.value) loadingDetail.value = false
  }
}

const loadInstitutionAuditEvents = async (institutionId) => {
  if (!institutionId || !canManageInstitution.value) {
    auditEvents.value = []
    auditPagination.page = 1
    auditPagination.per_page = 10
    auditPagination.total = 0
    auditPagination.pages = 1
    return
  }
  loadingAudit.value = true
  try {
    const response = await institutionService.listAuditEvents(institutionId, {
      page: 1,
      per_page: auditPagination.per_page,
    })
    if (institutionId !== selectedInstitutionId.value) return
    auditEvents.value = response.data?.audit_events || []
    const pagination = response.data?.pagination || {}
    auditPagination.page = pagination.page || 1
    auditPagination.per_page = pagination.per_page || auditPagination.per_page
    auditPagination.total = pagination.total || 0
    auditPagination.pages = pagination.pages || 1
  } catch (error) {
    if (institutionId !== selectedInstitutionId.value) return
    auditEvents.value = []
    toast.error(error?.error?.message || error?.message || 'Failed to load institution audit history')
  } finally {
    if (institutionId === selectedInstitutionId.value) loadingAudit.value = false
  }
}

const loadInstitutions = async (preferredId) => {
  loadingInstitutions.value = true
  try {
    await refreshAuthUser()
    if (isAdmin.value) adminInstitutions.value = (await institutionService.listInstitutions({ all: true })).data?.institutions || []
    const candidates = [preferredId, Number(route.query.workspace), selectedInstitutionId.value, authStore.user?.default_institution_id]
    selectedInstitutionId.value = candidates.find(id => institutionOptions.value.some(institution => institution.id === id))
      || institutionOptions.value[0]?.id || null
    await loadInstitutionDetail(selectedInstitutionId.value)
  } catch (error) {
    toast.error(error?.error?.message || 'Failed to load institution workspaces')
  } finally {
    loadingInstitutions.value = false
  }
}

const selectInstitution = async (institutionId) => {
  selectedInstitutionId.value = institutionId
  const query = { ...route.query, workspace: String(institutionId) }
  delete query.section
  router.replace({ query })
  await loadInstitutionDetail(institutionId)
}

const openApprovedWorkspace = (institutionId) => loadInstitutions(institutionId)

const createInstitution = async () => {
  creatingInstitution.value = true
  try {
    const response = await institutionService.createInstitution({ name: createForm.name })
    createForm.name = ''
    toast.success('Institution created successfully')
    await loadInstitutions(response.data?.institution?.id)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to create institution')
  } finally {
    creatingInstitution.value = false
  }
}

const saveInstitution = async () => {
  if (!selectedInstitution.value || !canManageInstitution.value) return
  savingInstitution.value = true
  try {
    const payload = { description: institutionForm.description }
    if (isAdmin.value) payload.name = institutionForm.name
    if (institutionForm.profileVisibility !== (selectedInstitution.value.profile_visibility || 'private')) {
      payload.profile_visibility = institutionForm.profileVisibility
    }
    const response = await institutionService.updateInstitution(selectedInstitution.value.id, payload)
    selectedInstitution.value = response.data?.institution || selectedInstitution.value
    await loadInstitutionAuditEvents(selectedInstitution.value.id)
    await loadInstitutions(selectedInstitution.value.id)
    toast.success('Institution updated successfully')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update institution')
  } finally {
    savingInstitution.value = false
  }
}

const updateMembershipRole = async (membership, role) => {
  if (!selectedInstitution.value) return
  try {
    await institutionService.updateMembership(selectedInstitution.value.id, membership.user_id, { role })
    await loadInstitutionDetail(selectedInstitution.value.id)
    toast.success('Membership updated')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update membership')
  }
}

const removeMembership = async (membership) => {
  if (!selectedInstitution.value) return
  try {
    await institutionService.deleteMembership(selectedInstitution.value.id, membership.user_id)
    await loadInstitutionDetail(selectedInstitution.value.id)
    await refreshAuthUser()
    toast.success('Membership removed')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to remove membership')
  }
}

const addCommunity = async () => {
  if (!selectedInstitution.value) return
  savingCommunity.value = true
  try {
    await institutionService.createCommunity(selectedInstitution.value.id, {
      identifier: communityForm.identifier,
      enabled: communityForm.enabled,
      is_primary_submission: communityForm.is_primary_submission,
      is_moderation_default: communityForm.is_moderation_default,
      sort_order: communityForm.sort_order,
    })
    communityForm.identifier = ''
    communityForm.enabled = true
    communityForm.is_primary_submission = false
    communityForm.is_moderation_default = false
    communityForm.sort_order = 0
    await loadInstitutionDetail(selectedInstitution.value.id)
    toast.success('Community added')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to add community')
  } finally {
    savingCommunity.value = false
  }
}

const updateCommunityPolicy = async (community, payload, successMessage) => {
  if (!selectedInstitution.value) return
  try {
    await institutionService.updateCommunity(selectedInstitution.value.id, community.id, payload)
    await loadInstitutionDetail(selectedInstitution.value.id)
    toast.success(successMessage)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update community')
  }
}

const toggleCommunity = async (community) => {
  await updateCommunityPolicy(community, { enabled: !community.enabled }, 'Community updated')
}

const togglePrimaryCommunity = async (community) => {
  await updateCommunityPolicy(
    community,
    { is_primary_submission: !community.is_primary_submission },
    'Primary submission community updated',
  )
}

const toggleModerationDefault = async (community) => {
  await updateCommunityPolicy(
    community,
    { is_moderation_default: !community.is_moderation_default },
    'Moderation default updated',
  )
}

const updateCommunitySortOrder = async (community, value) => {
  await updateCommunityPolicy(
    community,
    { sort_order: Number(value) || 0 },
    'Community order updated',
  )
}

const removeCommunity = async (community) => {
  if (!selectedInstitution.value) return
  try {
    await institutionService.deleteCommunity(selectedInstitution.value.id, community.id)
    await loadInstitutionDetail(selectedInstitution.value.id)
    toast.success('Community removed')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to remove community')
  }
}

const saveInstitutionCredential = async (environment) => {
  const state = institutionCredentialState[environment]
  state.saving = true
  try {
    const response = await institutionService.saveZenodoCredential(selectedInstitution.value.id, environment, state.token)
    state.credential = response.data?.credential || null
    state.token = ''
    await loadInstitutionAuditEvents(selectedInstitution.value.id)
    toast.success(`${environment} credential saved`)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || `Failed to save ${environment} credential`)
  } finally {
    state.saving = false
  }
}

const validateInstitutionCredential = async (environment) => {
  const state = institutionCredentialState[environment]
  state.validating = true
  try {
    const response = await institutionService.validateZenodoCredential(selectedInstitution.value.id, environment)
    state.credential = response.data?.credential || null
    await loadInstitutionAuditEvents(selectedInstitution.value.id)
    toast.success(`${environment} credential validated`)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || `Failed to validate ${environment} credential`)
  } finally {
    state.validating = false
  }
}

const deleteInstitutionCredential = async (environment) => {
  const state = institutionCredentialState[environment]
  state.deleting = true
  try {
    await institutionService.deleteZenodoCredential(selectedInstitution.value.id, environment)
    state.credential = null
    state.token = ''
    await loadInstitutionAuditEvents(selectedInstitution.value.id)
    toast.success(`${environment} credential deleted`)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || `Failed to delete ${environment} credential`)
  } finally {
    state.deleting = false
  }
}

watch(
  () => route.query.workspace,
  (workspace) => {
    const id = Number(workspace)
    if (!Number.isSafeInteger(id) || id <= 0 || id === selectedInstitutionId.value) return
    if (institutionOptions.value.some(institution => institution.id === id)) {
      selectedInstitutionId.value = id
      loadInstitutionDetail(id)
    } else {
      loadInstitutions(id)
    }
  }
)

watch([memberHeading, () => route.query.section, () => route.query.workspace], ([heading, section, workspace]) => {
  if (section === 'members' && canManageInstitution.value && Number(workspace) === selectedInstitution.value?.id) {
    heading?.focus()
  }
}, { flush: 'post' })

loadInstitutions()
</script>
