<template>
  <section class="space-y-4 rounded-xl border border-gray-200 bg-white p-5 sm:p-6" aria-labelledby="workspace-requests-title">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="workspace-requests-title" class="text-lg font-semibold text-gray-950">{{ admin ? 'Workspace requests' : 'Request an institution workspace' }}</h2>
        <p class="mt-1 text-sm text-gray-600">
          {{ admin ? 'Review requests for official institution workspaces.' : 'A site administrator reviews your request. For an existing workspace, ask its manager for an invitation.' }}
        </p>
      </div>
      <button type="button" :disabled="loading || Boolean(working)" class="text-sm font-medium text-indigo-700 underline disabled:opacity-50" @click="load(page)">
        Refresh requests
      </button>
    </div>

    <form v-if="!admin" class="grid items-end gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]" @submit.prevent="submit">
      <label class="text-sm font-medium text-gray-900">
        Institution name
        <input v-model.trim="name" type="text" required minlength="2" maxlength="255" class="mt-1 block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
      </label>
      <label class="text-sm font-medium text-gray-900">
        What will the workspace be used for? <span class="font-normal text-gray-500">(optional)</span>
        <input v-model.trim="reason" type="text" maxlength="2000" class="mt-1 block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
      </label>
      <button type="submit" :disabled="Boolean(working)" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
        Submit request
      </button>
    </form>

    <label v-if="admin" class="inline-flex flex-wrap items-center gap-2 text-sm font-medium text-gray-900">
      Show requests
      <select v-model="statusFilter" class="rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" @change="load(1)">
        <option value="pending">Pending</option>
        <option value="approved">Approved</option>
        <option value="rejected">Rejected</option>
      </select>
    </label>

    <p v-if="notice" role="status" class="text-sm text-gray-800">{{ notice }}</p>
    <p v-if="error" role="alert" class="text-sm text-red-800">{{ error }}</p>
    <p v-if="loading" role="status" class="text-sm text-gray-600">Checking requests…</p>
    <p v-else-if="!requests.length" class="text-sm text-gray-600">{{ admin ? 'No requests in this view.' : 'You have no workspace requests.' }}</p>
    <ul v-else class="divide-y divide-gray-200">
      <li v-for="request in requests" :key="request.id" class="space-y-2 py-3">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="break-words text-sm font-semibold text-gray-950">{{ request.name }}</p>
            <p v-if="request.requester?.email" class="break-all text-sm text-gray-600">Requested by {{ request.requester.email }}</p>
          </div>
          <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium capitalize text-gray-800">{{ request.status }}</span>
        </div>
        <p v-if="request.reason" class="break-words text-sm text-gray-600">{{ request.reason }}</p>
        <p v-if="request.review_note" class="break-words text-sm text-gray-600">{{ request.review_note }}</p>
        <router-link v-if="request.institution_id" :to="{ path: '/account/institutions', query: { workspace: String(request.institution_id) } }"
          class="inline-block text-sm font-medium text-indigo-700 underline">Open workspace</router-link>
        <div v-if="admin && request.status === 'pending'" class="flex flex-wrap items-end gap-3">
          <label class="w-full text-sm font-medium text-gray-900 sm:max-w-md">
            Note to requester <span class="font-normal text-gray-500">(optional)</span>
            <input v-model.trim="notes[request.id]" type="text" maxlength="2000" class="mt-1 block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
          </label>
          <button type="button" :disabled="Boolean(working)" :aria-label="`Approve ${request.name}`"
            class="rounded-md border border-indigo-200 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50" @click="decide(request, 'approve')">Approve</button>
          <button type="button" :disabled="Boolean(working)" :aria-label="`Reject ${request.name}`"
            class="rounded-md border border-red-200 px-3 py-2 text-sm font-medium text-red-800 hover:bg-red-50 disabled:opacity-50" @click="decide(request, 'reject')">Reject</button>
        </div>
      </li>
    </ul>
    <div v-if="pages > 1" class="flex flex-wrap items-center gap-4 text-sm text-gray-700">
      <button type="button" :disabled="loading || page <= 1" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="load(page - 1)">Previous</button>
      <span>Page {{ page }} of {{ pages }}</span>
      <button type="button" :disabled="loading || page >= pages" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="load(page + 1)">Next</button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import institutionService from '@/services/institution.service'
import { identityActionError } from '@/utils/emailAction'

const props = defineProps({ admin: Boolean })
const emit = defineEmits(['approved'])
const requests = ref([])
const name = ref('')
const reason = ref('')
const statusFilter = ref('pending')
const notes = reactive({})
const page = ref(1)
const pages = ref(1)
const loading = ref(false)
const working = ref('')
const error = ref('')
const notice = ref('')
let listRequest = 0

async function load(requestedPage = 1) {
  const version = ++listRequest
  loading.value = true
  error.value = ''
  try {
    const params = { page: requestedPage, per_page: 10 }
    if (props.admin) Object.assign(params, { all: true, status: statusFilter.value })
    const response = await institutionService.listWorkspaceRequests(params)
    if (version !== listRequest) return
    requests.value = response.data?.requests || []
    page.value = response.data?.pagination?.page || 1
    pages.value = response.data?.pagination?.pages || 1
  } catch (err) {
    if (version === listRequest) error.value = identityActionError(err, 'Could not load workspace requests. Refresh to try again.')
  } finally {
    if (version === listRequest) loading.value = false
  }
}

async function submit() {
  if (working.value) return
  working.value = 'submit'
  error.value = ''
  notice.value = ''
  try {
    await institutionService.requestWorkspace({ name: name.value, reason: reason.value })
    name.value = ''
    reason.value = ''
    notice.value = 'Workspace request sent for review.'
    await load(1)
  } catch (err) {
    error.value = identityActionError(err, 'Could not submit the workspace request.')
  } finally {
    working.value = ''
  }
}

async function decide(request, decision) {
  if (working.value) return
  working.value = request.id
  error.value = ''
  notice.value = ''
  try {
    const response = await institutionService.decideWorkspaceRequest(request.id, { decision, note: notes[request.id] || '' })
    delete notes[request.id]
    if (decision === 'approve') {
      notice.value = 'Workspace approved. The requester is its owner.'
      emit('approved', response.data?.request?.institution_id)
    } else {
      notice.value = 'Workspace request rejected.'
    }
    await load(1)
  } catch (err) {
    error.value = identityActionError(err, 'Could not record this decision.')
  } finally {
    working.value = ''
  }
}

onMounted(() => load(1))
</script>
