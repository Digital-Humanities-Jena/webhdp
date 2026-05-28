<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-6">
      <h1 class="text-3xl font-bold text-gray-900">My Submissions</h1>
      <p class="mt-1 text-gray-600">A history of all your processing submissions.</p>
    </div>

    <div class="bg-white shadow rounded-lg">
      <div v-if="loading" class="p-6 text-center">
        <LoadingSpinner size="lg" text="Loading submissions..." />
      </div>

      <div v-else-if="submissions.length === 0" class="p-6 text-center">
        <p class="text-gray-500">You have not made any submissions yet.</p>
      </div>

      <table v-else class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Pipeline</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Submitted</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
          </tr>
        </thead>
        <tbody class="bg-white divide-y divide-gray-200">
          <tr v-for="submission in submissions" :key="submission.id" class="hover:bg-gray-50">
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ submission.id }}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ submission.pipeline_id }}</td>
            <td class="px-6 py-4 whitespace-nowrap">
              <span
                :class="[
                  'px-2 py-1 text-xs font-medium rounded-full',
                  statusClass(submission.status)
                ]"
              >
                {{ submission.status }}
              </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
              {{ formatDate(submission.created_at) }}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
              <router-link
                :to="`/submissions/${submission.id}`"
                class="text-indigo-600 hover:text-indigo-900"
              >
                View Details
              </router-link>
              <router-link
                v-if="submission.session_id"
                :to="`/sessions/${submission.session_id}/records`"
                class="ml-4 text-slate-600 hover:text-slate-900"
              >
                Session Records
              </router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import submissionService from '@/services/submission.service.js'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'

const loading = ref(true)
const submissions = ref([])

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleString()
}

const statusClass = (status) => {
  switch (status) {
    case 'completed': return 'bg-green-100 text-green-800'
    case 'processing': return 'bg-yellow-100 text-yellow-800'
    case 'failed': return 'bg-red-100 text-red-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}

onMounted(async () => {
  try {
    const response = await submissionService.listSubmissions()
    submissions.value = response.data.submissions || []
  } catch (err) {
    console.error('Failed to load submissions:', err)
  } finally {
    loading.value = false
  }
})
</script>
