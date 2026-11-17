<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <section class="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div class="flex flex-col gap-4 border-b border-gray-200 px-6 py-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">Admin</p>
            <h1 class="mt-2 text-2xl font-semibold text-gray-900">HPC Access</h1>
            <p class="mt-2 text-sm text-gray-600">Review resource requests and manage accounts with HPC access.</p>
          </div>
          <div class="inline-flex rounded-md border border-gray-200 bg-gray-100 p-1">
            <button
              type="button"
              class="rounded px-3 py-1.5 text-sm font-medium"
              :class="activeTab === 'requests' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'"
              @click="activeTab = 'requests'"
            >
              Requests
            </button>
            <button
              type="button"
              class="rounded px-3 py-1.5 text-sm font-medium"
              :class="activeTab === 'access' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'"
              @click="activeTab = 'access'"
            >
              Accounts
            </button>
            <button
              type="button"
              class="rounded px-3 py-1.5 text-sm font-medium"
              :class="activeTab === 'reservations' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'"
              @click="activeTab = 'reservations'"
            >
              Reserved GPUs
            </button>
          </div>
        </div>

        <div v-if="activeTab === 'requests'" class="p-6">
          <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
            <select v-model="requestStatus" class="rounded-md border-gray-300 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500" @change="loadRequests">
              <option value="pending">Pending</option>
              <option value="all">All requests</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
            <button type="button" class="rounded-md border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50" @click="loadRequests">Refresh</button>
          </div>

          <div v-if="loadingRequests" class="py-10 text-center text-sm text-gray-500">Loading HPC requests...</div>
          <div v-else-if="requests.length === 0" class="py-10 text-center text-sm text-gray-500">No HPC requests found.</div>
          <div v-else class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Requester</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Use cases</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Status</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Submitted</th>
                  <th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 bg-white">
                <tr v-for="request in requests" :key="request.id">
                  <td class="px-4 py-4 text-sm text-gray-900">
                    <p class="font-medium">{{ request.full_name }}</p>
                    <p class="text-xs text-gray-500">{{ request.user?.email }}</p>
                    <p class="text-xs text-gray-500">{{ request.affiliation }}</p>
                  </td>
                  <td class="px-4 py-4 text-sm text-gray-700">{{ request.use_cases.join(', ') }}</td>
                  <td class="px-4 py-4 text-sm">
                    <span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="statusClass(request.status)">{{ request.status }}</span>
                  </td>
                  <td class="px-4 py-4 text-sm text-gray-500">{{ formatDate(request.submitted_at) }}</td>
                  <td class="px-4 py-4 text-right text-sm">
                    <div v-if="request.status === 'pending'" class="flex justify-end gap-2">
                      <button type="button" class="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700" @click="openReviewModal(request, 'approve')">Approve</button>
                      <button type="button" class="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="openReviewModal(request, 'reject')">Reject</button>
                    </div>
                    <span v-else class="text-xs text-gray-500">{{ request.review_comment || 'Reviewed' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="activeTab === 'access'" class="p-6">
          <div class="mb-4 flex justify-end">
            <button type="button" class="rounded-md border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50" @click="loadAccessUsers">Refresh</button>
          </div>
          <div v-if="loadingAccess" class="py-10 text-center text-sm text-gray-500">Loading HPC access accounts...</div>
          <div v-else-if="accessUsers.length === 0" class="py-10 text-center text-sm text-gray-500">No accounts have HPC access.</div>
          <div v-else class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">User</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Source</th>
                  <th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 bg-white">
                <tr v-for="user in accessUsers" :key="user.id">
                  <td class="px-4 py-4 text-sm text-gray-900">
                    <p class="font-medium">{{ user.email }}</p>
                    <p class="text-xs text-gray-500">{{ user.full_name || user.display_name || 'No name set' }}</p>
                  </td>
                  <td class="px-4 py-4 text-sm text-gray-700">{{ user.hpc_access_source === 'implicit_admin' ? 'Admin implicit access' : 'Explicit capability' }}</td>
                  <td class="px-4 py-4 text-right">
                    <button
                      type="button"
                      :disabled="user.hpc_access_source === 'implicit_admin'"
                      class="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      @click="revoke(user)"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <AdminGpuReservations v-else />
      </section>
    </div>

    <div
      v-if="reviewModal.open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="hpc-review-title"
      @click.self="closeReviewModal"
    >
      <section class="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div class="border-b border-gray-200 px-5 py-4">
          <p class="text-xs font-semibold uppercase tracking-wide" :class="reviewModal.action === 'approve' ? 'text-emerald-700' : 'text-rose-700'">
            {{ reviewModal.action === 'approve' ? 'Approve request' : 'Reject request' }}
          </p>
          <h2 id="hpc-review-title" class="mt-1 text-lg font-semibold text-gray-900">
            {{ reviewModal.request?.full_name || 'HPC resource request' }}
          </h2>
          <p class="mt-1 text-sm text-gray-600">
            {{ reviewModal.request?.user?.email }}
          </p>
        </div>
        <div class="space-y-4 px-5 py-4">
          <dl class="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt class="font-medium text-gray-700">Affiliation</dt>
              <dd class="mt-1 text-gray-600">{{ reviewModal.request?.affiliation || 'Not provided' }}</dd>
            </div>
            <div>
              <dt class="font-medium text-gray-700">Use cases</dt>
              <dd class="mt-1 text-gray-600">{{ reviewModal.request?.use_cases?.join(', ') || 'Not provided' }}</dd>
            </div>
          </dl>
          <label class="block text-sm font-medium text-gray-700">
            {{ reviewModal.action === 'approve' ? 'Approval note' : 'Rejection note' }}
            <textarea
              v-model.trim="reviewModal.comment"
              rows="4"
              class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
              :placeholder="reviewModal.action === 'approve' ? 'Optional note for this approval' : 'Optional note for this rejection'"
            ></textarea>
          </label>
        </div>
        <div class="flex justify-end gap-3 border-t border-gray-200 px-5 py-4">
          <button type="button" class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50" @click="closeReviewModal">
            Cancel
          </button>
          <button
            type="button"
            :disabled="reviewing"
            class="rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            :class="reviewModal.action === 'approve' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-rose-600 hover:bg-rose-700'"
            @click="submitReview"
          >
            {{ reviewing ? 'Saving...' : reviewModal.action === 'approve' ? 'Approve request' : 'Reject request' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import adminService from '@/services/admin.service'
import { useToast } from '@/composables/useToast'
import AdminGpuReservations from '@/components/hpc/AdminGpuReservations.vue'

const toast = useToast()
const activeTab = ref('requests')
const requestStatus = ref('pending')
const requests = ref([])
const accessUsers = ref([])
const loadingRequests = ref(false)
const loadingAccess = ref(false)
const reviewing = ref(false)
const reviewModal = ref({
  open: false,
  action: 'approve',
  request: null,
  comment: '',
})

const formatDate = (value) => value ? new Date(value).toLocaleString() : 'N/A'
const statusClass = (status) => {
  if (status === 'approved') return 'bg-emerald-100 text-emerald-700'
  if (status === 'rejected') return 'bg-rose-100 text-rose-700'
  return 'bg-amber-100 text-amber-800'
}

const loadRequests = async () => {
  loadingRequests.value = true
  try {
    const response = await adminService.listHpcResourceRequests({ status: requestStatus.value })
    requests.value = response.data?.requests || []
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to load HPC requests')
  } finally {
    loadingRequests.value = false
  }
}

const loadAccessUsers = async () => {
  loadingAccess.value = true
  try {
    const response = await adminService.listHpcAccessUsers()
    accessUsers.value = response.data?.users || []
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to load HPC access users')
  } finally {
    loadingAccess.value = false
  }
}

const openReviewModal = (request, action) => {
  reviewModal.value = {
    open: true,
    action,
    request,
    comment: '',
  }
}

const closeReviewModal = () => {
  if (reviewing.value) return
  reviewModal.value = {
    open: false,
    action: 'approve',
    request: null,
    comment: '',
  }
}

const submitReview = async () => {
  const { request, action, comment } = reviewModal.value
  if (!request) return
  reviewing.value = true
  try {
    if (action === 'approve') {
      await adminService.approveHpcResourceRequest(request.id, { comment })
      toast.success('HPC request approved')
    } else {
      await adminService.rejectHpcResourceRequest(request.id, { comment })
      toast.success('HPC request rejected')
    }
    reviewModal.value.open = false
    await Promise.all([loadRequests(), loadAccessUsers()])
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to review HPC request')
  } finally {
    reviewing.value = false
  }
}

const revoke = async (user) => {
  if (!window.confirm(`Revoke HPC access for ${user.email}?`)) return
  try {
    await adminService.revokeHpcAccess(user.id)
    toast.success('HPC access revoked')
    await loadAccessUsers()
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to revoke HPC access')
  }
}

watch(activeTab, (tab) => {
  if (tab === 'access') loadAccessUsers()
})

loadRequests()
loadAccessUsers()
</script>
