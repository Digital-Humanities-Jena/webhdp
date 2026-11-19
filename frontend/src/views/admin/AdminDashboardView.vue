<template>
  <div class="min-h-screen bg-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

      <div v-if="authStore.user?.role === 'admin'" class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <div class="bg-white rounded-lg shadow p-6">
          <div class="flex items-center">
            <div class="flex-shrink-0 bg-indigo-500 rounded-md p-3">
              <svg class="h-6 w-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            </div>
            <div class="ml-4">
              <p class="text-sm font-medium text-gray-500">Total Users</p>
              <p class="text-2xl font-semibold text-gray-900">{{ stats.totalUsers }}</p>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-lg shadow p-6">
          <div class="flex items-center">
            <div class="flex-shrink-0 bg-green-500 rounded-md p-3">
              <svg class="h-6 w-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div class="ml-4">
              <p class="text-sm font-medium text-gray-500">Total Sessions</p>
              <p class="text-2xl font-semibold text-gray-900">{{ stats.totalSessions }}</p>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-lg shadow p-6">
          <div class="flex items-center">
            <div class="flex-shrink-0 bg-yellow-500 rounded-md p-3">
              <svg class="h-6 w-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div class="ml-4">
              <p class="text-sm font-medium text-gray-500">Pending</p>
              <p class="text-2xl font-semibold text-gray-900">{{ stats.pendingSubmissions }}</p>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-lg shadow p-6">
          <div class="flex items-center">
            <div class="flex-shrink-0 bg-blue-500 rounded-md p-3">
              <svg class="h-6 w-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            </div>
            <div class="ml-4">
              <p class="text-sm font-medium text-gray-500">Completed</p>
              <p class="text-2xl font-semibold text-gray-900">{{ stats.completedSubmissions }}</p>
            </div>
          </div>
        </div>
      </div>

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8 mb-8">
        <div class="px-6 py-4 border-b border-gray-200">
          <h2 class="text-lg font-medium text-gray-900">Initial Setup Guidance</h2>
        </div>
        <div class="p-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <p class="max-w-3xl text-sm text-gray-600">
            Review mode-aware readiness for storage, compute, publishing, backups, and observability before opening workflows to users.
          </p>
          <router-link
            to="/admin/setup"
            class="inline-flex items-center justify-center rounded-md border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
            data-testid="admin-setup-guidance-link"
          >
            Open Operational Readiness
          </router-link>
        </div>
      </div>

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8 mb-8">
        <div class="px-6 py-4 border-b border-gray-200">
          <h2 class="text-lg font-medium text-gray-900">System Management</h2>
        </div>
        <div class="p-6">
          <p class="text-sm text-gray-600 mb-4">
            Resetting the WebHDP will mark the system as uninitialized, forcing the setup wizard to run again for all users.
            This does not delete data but requires the system checks to be re-verified.
          </p>
          <button
            @click="handleResetSystem"
            class="px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
          >
            Reset WebHDP
          </button>
        </div>
      </div>

      <VersionDetectionPolicyCard v-if="authStore.user?.role === 'admin'" />

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8 mb-8">
        <div class="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 class="text-lg font-medium text-gray-900">HPC-Link Configuration</h2>
          <span
            v-if="hpcConfig.last_validation_status"
            class="rounded-full px-2.5 py-1 text-xs font-semibold"
            :class="hpcConfig.last_validation_status === 'valid' ? 'bg-green-100 text-green-800' : 'bg-rose-100 text-rose-800'"
          >
            {{ hpcConfig.last_validation_status }}
          </span>
        </div>
        <div class="p-6 space-y-4">
          <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <label class="flex items-center gap-2 text-sm text-gray-700">
              <input v-model="hpcConfig.enabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              Enable HPC-Link
            </label>
            <label class="flex items-center gap-2 text-sm text-gray-700">
              <input v-model="hpcConfig.require_for_components" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              Require HPC-Link for HDP Components
            </label>
            <div class="text-sm text-gray-500">
              Token: {{ hpcConfig.has_token ? hpcConfig.masked_token_preview : 'not set' }}
            </div>
          </div>

          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <label class="text-sm text-gray-700">
              Base URL
              <input v-model="hpcConfig.base_url" type="url" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              Service token
              <input v-model="hpcTokenInput" type="password" autocomplete="new-password" placeholder="Leave blank to keep current token" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              Partition
              <input v-model="hpcConfig.default_partition" type="text" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              Duration (minutes)
              <input v-model.number="hpcConfig.default_duration_minutes" type="number" min="1" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              GPU count
              <input v-model.number="hpcConfig.default_gpu_count" type="number" min="0" max="4" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
              <span class="mt-1 block text-xs text-gray-500">Use 0 for CPU-only allocation targets.</span>
            </label>
            <label class="text-sm text-gray-700">
              Global allocation limit
              <input v-model.number="hpcConfig.max_active_allocations" type="number" min="1" max="20" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              Max per user
              <input v-model.number="hpcConfig.max_active_allocations_per_user" type="number" min="1" max="20" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
            <label class="text-sm text-gray-700">
              GPU type
              <input v-model="hpcConfig.default_gpu_type" type="text" placeholder="optional" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </label>
          </div>

          <p v-if="hpcConfig.last_validation_error" class="text-sm text-rose-700">
            {{ hpcConfig.last_validation_error }}
          </p>
          <div class="flex flex-wrap gap-3">
            <button
              type="button"
              class="px-4 py-2 text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60"
              :disabled="savingHpcConfig"
              @click="saveHpcConfig"
            >
              {{ savingHpcConfig ? 'Saving...' : 'Save HPC-Link config' }}
            </button>
            <button
              type="button"
              class="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60"
              :disabled="validatingHpcConfig"
              @click="validateHpcConfig"
            >
              {{ validatingHpcConfig ? 'Validating...' : 'Validate connection' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8 mb-8">
        <div class="px-6 py-4 border-b border-gray-200">
          <h2 class="text-lg font-medium text-gray-900">Import .hdpc for User</h2>
        </div>
        <div class="p-6 space-y-4">
          <p class="text-sm text-gray-600">
            Upload an exported `.hdpc` file and assign it to a user. Imported records become available in that user's Records Explorer.
          </p>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <select
              v-model.number="adminHdpcTargetUserId"
              :disabled="loadingUsers || importingHdpc"
              class="px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option :value="null">Select user</option>
              <option v-for="user in users" :key="`hdpc-target-${user.id}`" :value="user.id">
                {{ user.email }} (ID {{ user.id }})
              </option>
            </select>
            <input
              ref="adminHdpcInput"
              type="file"
              accept=".hdpc"
              :disabled="importingHdpc"
              class="px-3 py-2 border border-gray-300 rounded-md text-sm"
              @change="handleAdminHdpcFileChange"
            />
            <button
              type="button"
              class="px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed"
              :disabled="importingHdpc || !adminHdpcTargetUserId || !adminHdpcFile"
              @click="handleAdminHdpcImport"
            >
              {{ importingHdpc ? 'Importing...' : 'Import .hdpc' }}
            </button>
          </div>
          <p v-if="lastHdpcImport" class="text-xs text-gray-600">
            Imported session #{{ lastHdpcImport.session?.id }} for {{ lastHdpcImport.user?.email || `user #${lastHdpcImport.user?.id}` }}
            ({{ lastHdpcImport.import_summary?.record_count ?? 0 }} records).
          </p>
        </div>
      </div>

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8 mb-8">
        <div class="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 class="text-lg font-medium text-gray-900">Running Upload Operations</h2>
          <button
            type="button"
            class="px-3 py-1 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-full hover:bg-indigo-50"
            @click="loadRunningUploads"
          >
            Refresh
          </button>
        </div>

        <div v-if="loadingUploads" class="p-6 text-center text-sm text-gray-500">
          Loading running uploads...
        </div>

        <div v-else-if="runningUploads.length === 0" class="p-6 text-center text-sm text-gray-500">
          No upload operations are currently running.
        </div>

        <table v-else class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Session</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stage</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Progress</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Updated</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr v-for="operation in runningUploads" :key="operation.session_id" class="hover:bg-gray-50">
              <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">#{{ operation.session_id }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ operation.user_email }}</td>
              <td class="px-6 py-4 text-sm text-gray-600">
                <div class="font-medium text-gray-900">{{ operation.progress?.current_stage }}</div>
                <div class="text-xs text-gray-500">{{ operation.progress?.status_message }}</div>
              </td>
              <td class="px-6 py-4 text-sm text-gray-600">
                {{ operation.progress?.processed_count || 0 }} / {{ operation.progress?.total_files || 0 }}
                ({{ Math.round(operation.progress?.percent || 0) }}%)
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {{ formatDate(operation.progress?.updated_at || operation.updated_at) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="bg-white shadow rounded-lg">
        <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h2 class="text-lg font-medium text-gray-900">All Submissions</h2>
          <div class="flex space-x-2">
            <select v-model="filterStatus" class="px-3 py-1 border border-gray-300 rounded-md text-sm">
              <option value="">All Status</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
          </div>
        </div>

        <div v-if="loading" class="p-6 text-center">
          <LoadingSpinner size="lg" text="Loading submissions..." />
        </div>

        <div v-else-if="filteredSubmissions.length === 0" class="p-6 text-center">
          <p class="text-gray-500">No submissions found</p>
        </div>

        <table v-else class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Pipeline</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr v-for="submission in filteredSubmissions" :key="submission.id" class="hover:bg-gray-50">
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ submission.id }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ submission.user_email }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ submission.pipeline_id }}</td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span
                  :class="[
                    'px-2 py-1 text-xs font-medium rounded-full',
                    submission.status === 'completed' ? 'bg-green-100 text-green-800' :
                    submission.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                    submission.status === 'failed' ? 'bg-red-100 text-red-800' :
                    'bg-gray-100 text-gray-800'
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
                  :to="`/admin/review/${submission.id}`"
                  class="text-indigo-600 hover:text-indigo-900"
                >
                  Review
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="authStore.user?.role === 'admin'" class="bg-white shadow rounded-lg mt-8">
        <div class="px-6 py-4 border-b border-gray-200">
          <h2 class="text-lg font-medium text-gray-900">User Management</h2>
        </div>

        <div v-if="loadingUsers" class="p-6 text-center">
          <LoadingSpinner size="lg" text="Loading users..." />
        </div>

        <table v-else class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User ID</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Current Role</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Capabilities / Groups</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Change Role</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Recovery</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr v-for="user in users" :key="user.id">
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ user.id }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ user.email }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ user.role }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                <div class="flex flex-col gap-2">
                  <label class="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="Array.isArray(user.capabilities) && user.capabilities.includes('native_pipeline_author')"
                      :disabled="user.role === 'admin'"
                      @change="updateCapability(user.id, 'native_pipeline_author', $event.target.checked)"
                    />
                    <span>native_pipeline_author</span>
                  </label>
                  <label class="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="Array.isArray(user.capabilities) && user.capabilities.includes('developer_access')"
                      :disabled="user.role === 'admin'"
                      @change="updateCapability(user.id, 'developer_access', $event.target.checked)"
                    />
                    <span>Developer group</span>
                  </label>
                  <label class="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="Array.isArray(user.capabilities) && user.capabilities.includes('hpc_link_access')"
                      :disabled="user.role === 'admin'"
                      @change="updateCapability(user.id, 'hpc_link_access', $event.target.checked)"
                    />
                    <span>hpc_link_access</span>
                  </label>
                  <label class="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="Array.isArray(user.capabilities) && user.capabilities.includes('mounted_input_access')"
                      :disabled="user.role === 'admin'"
                      @change="updateCapability(user.id, 'mounted_input_access', $event.target.checked)"
                    />
                    <span>Mounted input access</span>
                  </label>
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                <select
                  @change="updateRole(user.id, $event.target.value)"
                  :value="user.role"
                  :disabled="user.id === authStore.user.id"
                  class="px-3 py-1 border border-gray-300 rounded-md text-sm disabled:opacity-50 disabled:bg-gray-100"
                  title="Admins cannot change their own role"
                >
                  <option value="user">user</option>
                  <option value="moderator">moderator</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                <div class="mb-3 space-y-1 text-xs text-gray-600" data-testid="admin-recovery-visibility">
                  <p>
                    <span class="font-medium text-gray-800">{{ user.recovery_codes?.remaining_count ?? 0 }}</span>
                    user recovery code{{ (user.recovery_codes?.remaining_count ?? 0) === 1 ? '' : 's' }} available
                  </p>
                  <p v-if="user.admin_recovery_codes?.remaining_count">
                    <span class="font-medium text-gray-800">{{ user.admin_recovery_codes.remaining_count }}</span>
                    admin-issued one-time code{{ user.admin_recovery_codes.remaining_count === 1 ? '' : 's' }} pending
                  </p>
                  <p v-if="user.force_password_change" class="font-medium text-amber-700">Password change required</p>
                  <p v-if="user.last_recovery_reset_at">Last reset {{ formatDate(user.last_recovery_reset_at) }}</p>
                </div>
                <button
                  type="button"
                  :disabled="user.id === authStore.user.id"
                  class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50 disabled:bg-gray-100 disabled:text-gray-500 disabled:border-gray-200"
                  @click="openRecoveryReset(user)"
                >
                  Account recovery
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="recoveryReset.open" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4">
        <div class="w-full max-w-lg rounded-lg bg-white shadow-xl">
          <div class="border-b border-gray-200 px-6 py-4">
            <h2 class="text-lg font-semibold text-gray-900">Account Recovery</h2>
            <p class="mt-1 text-sm text-gray-500">{{ recoveryReset.user?.email }}</p>
          </div>
          <div class="space-y-4 p-6">
            <div v-if="!recoveryReset.result" class="space-y-4">
              <p class="text-sm text-gray-600">
                Create a temporary password and one-time MFA recovery code for out-of-band handoff.
              </p>
              <label class="block text-sm text-gray-700">
                Temporary password
                <input
                  v-model="recoveryReset.temporaryPassword"
                  type="text"
                  autocomplete="off"
                  placeholder="Leave blank to generate"
                  class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </label>
            </div>
            <div v-else data-testid="admin-recovery-result" class="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <p class="text-sm font-semibold text-amber-900">Share these values securely now. They will not be shown again.</p>
              <dl class="mt-3 space-y-2 text-sm">
                <div>
                  <dt class="font-medium text-gray-700">Temporary password</dt>
                  <dd class="font-mono text-gray-900">{{ recoveryReset.result.temporary_password }}</dd>
                </div>
                <div>
                  <dt class="font-medium text-gray-700">One-time MFA recovery code</dt>
                  <dd class="font-mono text-gray-900">{{ recoveryReset.result.recovery_code }}</dd>
                </div>
                <div>
                  <dt class="font-medium text-gray-700">Recovery code expires</dt>
                  <dd class="text-gray-900">{{ formatDate(recoveryReset.result.recovery_code_expires_at) }}</dd>
                </div>
              </dl>
            </div>
          </div>
          <div class="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
            <button
              type="button"
              class="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
              @click="closeRecoveryReset"
            >
              Close
            </button>
            <button
              v-if="!recoveryReset.result"
              type="button"
              :disabled="recoveryReset.loading"
              data-testid="admin-recovery-submit"
              class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-60"
              @click="submitRecoveryReset"
            >
              {{ recoveryReset.loading ? 'Creating...' : 'Create recovery reset' }}
            </button>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import VersionDetectionPolicyCard from '@/components/admin/VersionDetectionPolicyCard.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import api from '@/services/api'
import submissionService from '@/services/submission.service.js'
import adminService from '@/services/admin.service'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const toast = useToast()

const loading = ref(true)
const submissions = ref([])
const filterStatus = ref('')
const stats = ref({
  totalUsers: 0,
  totalSessions: 0,
  pendingSubmissions: 0,
  completedSubmissions: 0
})

const users = ref([])
const loadingUsers = ref(false)
const adminHdpcTargetUserId = ref(null)
const adminHdpcFile = ref(null)
const adminHdpcInput = ref(null)
const importingHdpc = ref(false)
const lastHdpcImport = ref(null)
const runningUploads = ref([])
const loadingUploads = ref(false)
const hpcConfig = ref({
  enabled: false,
  require_for_components: false,
  base_url: '',
  has_token: false,
  masked_token_preview: '',
  default_partition: 'partition-a',
  default_gpu_type: '',
  default_gpu_count: 1,
  default_duration_minutes: 30,
  max_active_allocations: 3,
  max_active_allocations_per_user: 1,
  last_validation_status: null,
  last_validation_error: null
})
const hpcTokenInput = ref('')
const savingHpcConfig = ref(false)
const validatingHpcConfig = ref(false)
const recoveryReset = ref({
  open: false,
  user: null,
  temporaryPassword: '',
  loading: false,
  result: null
})
let uploadRefreshTimer = null

const filteredSubmissions = computed(() => {
  if (!filterStatus.value) return submissions.value
  return submissions.value.filter(s => s.status === filterStatus.value)
})

const formatDate = (dateString) => {
  const date = new Date(dateString)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
}

const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

const stopUploadRefresh = () => {
  if (uploadRefreshTimer) {
    window.clearTimeout(uploadRefreshTimer)
    uploadRefreshTimer = null
  }
}

const scheduleUploadRefresh = () => {
  stopUploadRefresh()
  if (runningUploads.value.length > 0) {
    uploadRefreshTimer = window.setTimeout(loadRunningUploads, 5000)
  }
}

const loadSubmissions = async () => {
  try {
    const response = await api.get('/admin/submissions')
    submissions.value = response.data.submissions || []
  } catch (err) {
    console.error('Failed to load submissions:', err)
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const response = await api.get('/admin/stats')
    const payload = response.data || {}
    stats.value.totalUsers = payload.total_users ?? stats.value.totalUsers
    stats.value.totalSessions = payload.total_sessions ?? stats.value.totalSessions
    stats.value.pendingSubmissions = payload.pending_submissions ?? stats.value.pendingSubmissions
    stats.value.completedSubmissions = payload.completed_submissions ?? stats.value.completedSubmissions
  } catch (err) {
    console.error('Failed to load admin stats:', err)
  }
}

const loadRunningUploads = async () => {
  if (authStore.user?.role !== 'admin') return

  loadingUploads.value = true
  try {
    const response = await submissionService.listAdminUploadOperations({ status: 'running' })
    runningUploads.value = response.data?.operations || []
  } catch (err) {
    console.error('Failed to load running uploads:', err)
  } finally {
    loadingUploads.value = false
    scheduleUploadRefresh()
  }
}

const loadHpcConfig = async () => {
  if (authStore.user?.role !== 'admin') return
  try {
    const response = await adminService.getHpcLinkConfig()
    hpcConfig.value = { ...hpcConfig.value, ...(response.data?.config || {}) }
  } catch (err) {
    console.error('Failed to load HPC-Link config:', err)
  }
}

const buildHpcConfigPayload = () => {
  const payload = {
    enabled: Boolean(hpcConfig.value.enabled),
    require_for_components: Boolean(hpcConfig.value.require_for_components),
    base_url: hpcConfig.value.base_url,
    default_partition: hpcConfig.value.default_partition,
    default_gpu_type: hpcConfig.value.default_gpu_type || null,
    default_gpu_count: Number(hpcConfig.value.default_gpu_count ?? 1),
    default_duration_minutes: Number(hpcConfig.value.default_duration_minutes || 30),
    max_active_allocations: Number(hpcConfig.value.max_active_allocations || 1),
    max_active_allocations_per_user: Number(hpcConfig.value.max_active_allocations_per_user || 1)
  }
  if (hpcTokenInput.value.trim()) {
    payload.token = hpcTokenInput.value.trim()
  }
  return payload
}

const saveHpcConfig = async () => {
  savingHpcConfig.value = true
  try {
    const response = await adminService.updateHpcLinkConfig(buildHpcConfigPayload())
    hpcConfig.value = { ...hpcConfig.value, ...(response.data?.config || {}) }
    hpcTokenInput.value = ''
    toast.success('HPC-Link configuration saved')
  } catch (err) {
    toast.error(err.error?.message || err.error || 'Failed to save HPC-Link configuration')
  } finally {
    savingHpcConfig.value = false
  }
}

const validateHpcConfig = async () => {
  validatingHpcConfig.value = true
  try {
    const response = await adminService.validateHpcLinkConfig()
    hpcConfig.value = { ...hpcConfig.value, ...(response.data?.config || {}) }
    toast.success('HPC-Link validation completed')
  } catch (err) {
    const config = err?.error?.details?.config || err?.details?.config
    if (config) {
      hpcConfig.value = { ...hpcConfig.value, ...config }
    }
    toast.error(err.error?.message || err.error || 'HPC-Link validation failed')
  } finally {
    validatingHpcConfig.value = false
  }
}

const loadUsers = async () => {
  if (authStore.user?.role === 'admin') {
    loadingUsers.value = true
    try {
      const response = await api.get('/admin/users')
      users.value = response.data.users || []
      if (!adminHdpcTargetUserId.value && users.value.length > 0) {
        adminHdpcTargetUserId.value = users.value[0].id
      }
    } catch (err) {
      console.error('Failed to load users:', err)
      toast.error('Failed to load users')
    } finally {
      loadingUsers.value = false
    }
  }
}

const handleAdminHdpcFileChange = (event) => {
  adminHdpcFile.value = event.target.files?.[0] || null
}

const handleAdminHdpcImport = async () => {
  if (!adminHdpcTargetUserId.value) {
    toast.error('Select a target user')
    return
  }
  if (!adminHdpcFile.value) {
    toast.error('Select a .hdpc file')
    return
  }

  importingHdpc.value = true
  try {
    const response = await submissionService.adminImportHdpcForUser(adminHdpcTargetUserId.value, adminHdpcFile.value)
    lastHdpcImport.value = response.data
    toast.success(
      `Imported .hdpc for ${response.data?.user?.email || `user #${adminHdpcTargetUserId.value}`}`
    )
    adminHdpcFile.value = null
    if (adminHdpcInput.value) {
      adminHdpcInput.value.value = ''
    }
  } catch (err) {
    console.error('Admin .hdpc import failed:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to import .hdpc file')
  } finally {
    importingHdpc.value = false
  }
}

const updateRole = async (userId, newRole) => {
  if (userId === authStore.user.id) {
    toast.warning("You cannot change your own role.");
    // reset dropdown
    const userIndex = users.value.findIndex(u => u.id === userId)
    if (userIndex !== -1) {
      users.value[userIndex].role = authStore.user.role;
    }
    return;
  }

  try {
    await api.put(`/admin/users/${userId}/role`, { role: newRole })
    toast.success('User role updated')
    // Refresh users list to show new role
    const userIndex = users.value.findIndex(u => u.id === userId)
    if (userIndex !== -1) {
      users.value[userIndex].role = newRole
    }
  } catch (err) {
    toast.error(err.error || 'Failed to update role')
  }
}

const updateCapability = async (userId, capability, enabled) => {
  const userIndex = users.value.findIndex((entry) => entry.id === userId)
  if (userIndex === -1) {
    return
  }
  const existing = Array.isArray(users.value[userIndex].capabilities) ? [...users.value[userIndex].capabilities] : []
  const next = enabled
    ? [...new Set([...existing, capability])]
    : existing.filter((entry) => entry !== capability)

  try {
    const response = await api.put(`/admin/users/${userId}/capabilities`, { capabilities: next })
    users.value[userIndex].capabilities = response.data?.capabilities || next
    toast.success('User capabilities updated')
  } catch (err) {
    toast.error(err.error || 'Failed to update capabilities')
  }
}

const openRecoveryReset = (user) => {
  recoveryReset.value = {
    open: true,
    user,
    temporaryPassword: '',
    loading: false,
    result: null
  }
}

const closeRecoveryReset = () => {
  recoveryReset.value = {
    open: false,
    user: null,
    temporaryPassword: '',
    loading: false,
    result: null
  }
}

const submitRecoveryReset = async () => {
  if (!recoveryReset.value.user) return
  recoveryReset.value.loading = true
  try {
    const payload = {}
    if (recoveryReset.value.temporaryPassword.trim()) {
      payload.temporary_password = recoveryReset.value.temporaryPassword.trim()
    }
    const response = await adminService.resetUserRecovery(recoveryReset.value.user.id, payload)
    recoveryReset.value.result = response.data
    if (response.data?.user) {
      const userIndex = users.value.findIndex((entry) => entry.id === response.data.user.id)
      if (userIndex !== -1) {
        users.value[userIndex] = { ...users.value[userIndex], ...response.data.user }
      }
    }
    toast.success('Account recovery reset created')
  } catch (err) {
    toast.error(err.error?.message || err.error || 'Failed to create account recovery reset')
  } finally {
    recoveryReset.value.loading = false
  }
}

const handleResetSystem = async () => {
  if (!confirm("Are you sure you want to reset the WebHDP setup state? This will force all users to the setup wizard.")) {
    return
  }

  try {
    await systemStore.resetSystem()
    toast.success('System reset successfully. Redirecting to setup...')
    router.push('/setup')
  } catch (err) {
    toast.error('Failed to reset system')
    console.error(err)
  }
}

onMounted(() => {
  loadStats()
  loadSubmissions()
  loadUsers()
  loadRunningUploads()
  loadHpcConfig()
})

onBeforeUnmount(() => {
  stopUploadRefresh()
})
</script>
