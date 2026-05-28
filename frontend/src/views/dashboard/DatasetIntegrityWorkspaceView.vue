<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-100">
    <div class="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold text-slate-900">Dataset Integrity Workspace</h1>
          <p class="mt-1 text-sm text-slate-600">
            Review authoritative dataset state, duplicate conflicts, repair drafts, and export bundles from one view.
          </p>
        </div>
        <button
          type="button"
          class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          :disabled="loading"
          @click="loadCurrent"
        >
          Refresh
        </button>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Loading dataset integrity workspace..." />

      <div v-else-if="error" class="rounded-xl border border-rose-200 bg-white p-6">
        <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
      </div>

      <div v-else class="space-y-6">
        <div class="rounded-xl border border-slate-200 bg-white p-4">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-end">
            <div class="flex-1">
              <label class="block text-sm font-medium text-slate-700">Dataset</label>
              <select
                v-model="selectedDatasetKey"
                class="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                @change="navigateToDataset"
              >
                <option value="">Choose a dataset</option>
                <option v-for="dataset in datasets" :key="dataset.dataset_key" :value="dataset.dataset_key">
                  {{ dataset.dataset_key }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-700">Environment</label>
              <select
                v-model="selectedEnvironment"
                class="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                <option value="production">Production</option>
                <option value="sandbox">Sandbox</option>
                <option value="all">All</option>
              </select>
            </div>
            <div v-if="selectedDatasetKey" class="text-xs text-slate-500">
              Route key: <span class="font-mono">{{ selectedDatasetKey }}</span>
            </div>
          </div>
        </div>

        <div v-if="!selectedDatasetKey" class="space-y-6">
          <div class="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div class="border-b border-slate-200 px-4 py-3">
              <h2 class="text-sm font-semibold text-slate-900">Discoverable Datasets</h2>
            </div>
            <div v-if="datasets.length === 0" class="p-6 text-sm text-slate-500">
              No datasets are currently discoverable from the available sessions.
            </div>
            <div v-else class="overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-200">
                <thead class="bg-slate-50">
                  <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Dataset</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Source Paths</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Published</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Duplicate Published</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Sessions</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white">
                  <tr v-for="dataset in datasets" :key="dataset.dataset_key">
                    <td class="px-4 py-3 text-sm font-medium text-slate-900">{{ dataset.dataset_key }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ dataset.source_path_count || 0 }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ dataset.published_source_path_count || 0 }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ dataset.duplicate_published_source_path_count || 0 }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ dataset.session_count || 0 }}</td>
                    <td class="px-4 py-3 text-sm">
                      <router-link
                        :to="buildDatasetRoute(dataset.dataset_key, { environment: selectedEnvironment })"
                        class="font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        Open Workspace
                      </router-link>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div
            v-if="isPrivileged"
            class="overflow-hidden rounded-xl border border-slate-200 bg-white"
          >
            <div class="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div>
                <h2 class="text-sm font-semibold text-slate-900">Admin Conflict Review</h2>
                <p class="mt-1 text-xs text-slate-500">
                  Cross-session duplicate datasets requiring operator review in the selected environment.
                </p>
              </div>
              <span class="text-xs text-slate-500">
                {{ globalConflictReviewCount }} duplicate group<span v-if="globalConflictReviewCount !== 1">s</span>
              </span>
            </div>
            <div v-if="reviewLoading" class="p-6 text-sm text-slate-500">
              Loading duplicate review queue...
            </div>
            <div v-else-if="!globalConflictReview.length" class="p-6 text-sm text-slate-500">
              No duplicate-review datasets were found for this environment.
            </div>
            <div v-else class="overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-200">
                <thead class="bg-slate-50">
                  <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Dataset</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Groups</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Published Duplicates</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Affected Users</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Preview</th>
                    <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white">
                  <tr v-for="item in globalConflictReview" :key="item.dataset_key">
                    <td class="px-4 py-3 text-sm font-medium text-slate-900">{{ item.dataset_key }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ item.duplicate_group_count || 0 }}</td>
                    <td class="px-4 py-3 text-sm text-slate-700">{{ item.duplicate_published_source_path_count || 0 }}</td>
                    <td class="px-4 py-3 text-xs text-slate-600">
                      <div v-if="item.affected_users?.length" class="space-y-1">
                        <p v-for="user in item.affected_users.slice(0, 3)" :key="`${item.dataset_key}-${user.user_id}`">
                          {{ user.email || `User ${user.user_id}` }}
                        </p>
                      </div>
                      <span v-else>Unknown</span>
                    </td>
                    <td class="px-4 py-3 text-xs text-slate-600">
                      <div v-if="item.groups_preview?.length" class="space-y-1">
                        <p
                          v-for="group in item.groups_preview"
                          :key="`${item.dataset_key}-${group.normalized_source_file_path}`"
                          class="break-all"
                        >
                          {{ group.normalized_source_file_path }}
                        </p>
                      </div>
                      <span v-else>No preview</span>
                    </td>
                    <td class="px-4 py-3 text-sm">
                      <router-link
                        :to="buildDatasetRoute(item.dataset_key, { tab: 'duplicates', environment: selectedEnvironment })"
                        class="font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        Open Review
                      </router-link>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <template v-else>
          <div class="grid grid-cols-2 gap-3 md:grid-cols-5">
            <div class="rounded-xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Source Paths</p>
              <p class="text-2xl font-bold text-slate-900">{{ summary.source_path_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-emerald-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-emerald-600">Published Paths</p>
              <p class="text-2xl font-bold text-emerald-700">{{ summary.published_source_path_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-rose-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-rose-600">Duplicate Published</p>
              <p class="text-2xl font-bold text-rose-700">{{ summary.duplicate_published_source_path_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-amber-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-amber-600">Unpublished Paths</p>
              <p class="text-2xl font-bold text-amber-700">{{ summary.unpublished_source_path_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-indigo-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-indigo-600">Authoritative Session</p>
              <p class="text-2xl font-bold text-indigo-700">{{ summary.authoritative_session_id || 'N/A' }}</p>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div class="rounded-xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Missing DOI (Primary)</p>
              <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.primary_missing_doi_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Missing GLB Link (Primary)</p>
              <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.primary_missing_glb_link_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Production Paths</p>
              <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.environment_breakdown?.production?.source_path_count || 0 }}</p>
              <p class="mt-1 text-xs text-slate-500">
                {{ summary.environment_breakdown?.production?.published_source_path_count || 0 }} published
              </p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-wide text-slate-500">Sandbox Paths</p>
              <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.environment_breakdown?.sandbox?.source_path_count || 0 }}</p>
              <p class="mt-1 text-xs text-slate-500">
                {{ summary.environment_breakdown?.sandbox?.published_source_path_count || 0 }} published
              </p>
            </div>
          </div>

          <div class="rounded-xl border border-slate-200 bg-white">
            <div class="flex flex-wrap gap-2 border-b border-slate-200 px-4 py-3">
              <button
                v-for="tab in tabs"
                :key="tab.id"
                type="button"
                class="rounded-lg border px-3 py-2 text-sm font-medium"
                :class="activeTab === tab.id ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
                @click="activeTab = tab.id"
              >
                {{ tab.label }}
              </button>
            </div>

            <div v-if="activeTab === 'overview'" class="space-y-4 p-4">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-end">
                <div>
                  <label class="block text-sm font-medium text-slate-700">Authoritative Session</label>
                  <select
                    v-model.number="selectedAuthoritativeSessionId"
                    class="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                  >
                    <option v-for="session in summary.sessions || []" :key="session.session_id" :value="session.session_id">
                      Session {{ session.session_id }} · {{ session.published_records }} published
                    </option>
                  </select>
                </div>
                <p class="text-xs text-slate-500">
                  Draft breakdown:
                  <span class="font-medium text-slate-700">{{ formatDraftBreakdown(summary.draft_breakdown) }}</span>
                </p>
              </div>

              <div
                v-if="selectedAuthoritativeSessionId"
                class="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4"
              >
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-slate-900">Authoritative Session Intelligence</p>
                    <p class="mt-1 text-xs text-slate-600">
                      Native `.hdpc` workspace summary for session {{ selectedAuthoritativeSessionId }}.
                    </p>
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <router-link
                      :to="{ name: 'SessionRecords', params: { sessionId: String(selectedAuthoritativeSessionId) } }"
                      class="rounded-lg border border-indigo-200 bg-white px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50"
                    >
                      Open Session
                    </router-link>
                    <router-link
                      :to="{ name: 'SessionProvenanceReport', params: { sessionId: String(selectedAuthoritativeSessionId) } }"
                      class="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Provenance Report
                    </router-link>
                  </div>
                </div>

                <p v-if="authoritativeSessionInsightError" class="mt-3 text-xs text-amber-700">
                  {{ authoritativeSessionInsightError }}
                </p>

                <div
                  v-else-if="authoritativeSessionInsight"
                  class="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5"
                >
                  <div class="rounded-lg border border-white/70 bg-white p-3">
                    <p class="text-[11px] uppercase tracking-wide text-slate-500">Prepared</p>
                    <p class="mt-1 text-xl font-bold text-amber-700">
                      {{ authoritativeSessionInsight.record_summary?.prepared_count || 0 }}
                    </p>
                  </div>
                  <div class="rounded-lg border border-white/70 bg-white p-3">
                    <p class="text-[11px] uppercase tracking-wide text-slate-500">Draft</p>
                    <p class="mt-1 text-xl font-bold text-sky-700">
                      {{ authoritativeSessionInsight.record_summary?.draft_count || 0 }}
                    </p>
                  </div>
                  <div class="rounded-lg border border-white/70 bg-white p-3">
                    <p class="text-[11px] uppercase tracking-wide text-slate-500">Published</p>
                    <p class="mt-1 text-xl font-bold text-emerald-700">
                      {{ authoritativeSessionInsight.record_summary?.published_count || 0 }}
                    </p>
                  </div>
                  <div class="rounded-lg border border-white/70 bg-white p-3">
                    <p class="text-[11px] uppercase tracking-wide text-slate-500">Uploadable</p>
                    <p class="mt-1 text-xl font-bold text-slate-900">
                      {{ authoritativeSessionInsight.upload_summary?.uploadable_item_count || 0 }}
                    </p>
                  </div>
                  <div class="rounded-lg border border-white/70 bg-white p-3">
                    <p class="text-[11px] uppercase tracking-wide text-slate-500">Latest Published</p>
                    <p class="mt-1 text-sm font-semibold text-slate-900">
                      {{ authoritativeSessionInsight.versioning_summary?.latest_published_record?.record_title || 'None yet' }}
                    </p>
                  </div>
                </div>
              </div>

              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200">
                  <thead class="bg-slate-50">
                    <tr>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Session</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Published</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Published Paths</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Drafts</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Prepared</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Total</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Latest Activity</th>
                      <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-100 bg-white">
                    <tr v-for="session in summary.sessions || []" :key="session.session_id">
                      <td class="px-4 py-3 text-sm font-medium text-slate-900">{{ session.session_id }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ session.published_records }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ session.published_source_path_count }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ session.draft_records }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ session.prepared_records }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ session.total_records }}</td>
                      <td class="px-4 py-3 text-sm text-slate-700">{{ formatDate(session.latest_activity) }}</td>
                      <td class="px-4 py-3 text-sm">
                        <router-link
                          :to="{ name: 'SessionRecords', params: { sessionId: String(session.session_id) } }"
                          class="font-medium text-indigo-600 hover:text-indigo-800"
                        >
                          Open Session
                        </router-link>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div v-else-if="activeTab === 'duplicates'" class="space-y-4 p-4">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p class="text-sm font-medium text-slate-900">Duplicate Groups</p>
                  <p class="mt-1 text-xs text-slate-500">
                    Filter to a single normalized source path for exact conflict review and versioning actions.
                  </p>
                </div>
                <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <input
                    v-model="pathFilterDraft"
                    type="text"
                    placeholder="Filter by normalized source path"
                    class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm sm:w-96"
                    @keyup.enter="applyPathFilter"
                  >
                  <div class="flex gap-2">
                    <button
                      type="button"
                      class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      @click="applyPathFilter"
                    >
                      Apply
                    </button>
                    <button
                      v-if="selectedPathFilter"
                      type="button"
                      class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
                      @click="clearPathFilter"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="selectedPathFilter" class="rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
                Showing the exact duplicate group for <span class="font-mono">{{ selectedPathFilter }}</span>.
              </div>

              <div v-if="!duplicates.length" class="text-sm text-slate-500">
                {{ selectedPathFilter ? 'No duplicate groups match the selected source path.' : 'No duplicate groups were detected for this dataset.' }}
              </div>

              <div v-for="group in duplicates" :key="group.normalized_source_file_path" class="rounded-xl border border-slate-200 p-4">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-slate-900">{{ group.normalized_source_file_path }}</p>
                    <p class="mt-1 text-xs text-slate-500">
                      {{ group.record_count }} rows · {{ group.published_record_count }} published · {{ group.lineage_count || 0 }} lineage<span v-if="(group.lineage_count || 0) !== 1">s</span>
                    </p>
                    <p v-if="group.affected_users?.length" class="mt-1 text-xs text-slate-500">
                      {{ group.affected_users.map((user) => user.email || `User ${user.user_id}`).join(' · ') }}
                    </p>
                  </div>
                  <div class="space-y-2 text-right">
                    <p class="text-xs text-amber-700">{{ group.recommended_action }}</p>
                    <button
                      v-if="selectedPathFilter !== group.normalized_source_file_path"
                      type="button"
                      class="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                      @click="focusDuplicateGroup(group.normalized_source_file_path)"
                    >
                      Open Exact Group
                    </button>
                  </div>
                </div>

                <div class="mt-3 overflow-x-auto">
                  <table class="min-w-full divide-y divide-slate-200">
                    <thead class="bg-slate-50">
                      <tr>
                        <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Record</th>
                        <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Status</th>
                        <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Owner</th>
                        <th class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 bg-white">
                      <tr v-for="record in group.records" :key="`${record.session_id}-${record.local_record_id}`">
                        <td class="px-3 py-2 text-sm text-slate-700">
                          <p class="font-medium text-slate-900">Session {{ record.session_id }} · Local {{ record.local_record_id }}</p>
                          <p class="mt-1 text-xs text-slate-500">{{ record.record_title || 'Untitled record' }}</p>
                          <p v-if="record.concept_rec_id" class="mt-1 text-xs text-slate-500">concept {{ record.concept_rec_id }}</p>
                        </td>
                        <td class="px-3 py-2 text-xs text-slate-600">
                          <span class="inline-flex rounded-full border border-slate-200 px-2 py-1 font-medium text-slate-700">
                            {{ record.record_status }}
                          </span>
                        </td>
                        <td class="px-3 py-2 text-xs text-slate-600">
                          {{ record.session_owner_email || (record.session_user_id ? `User ${record.session_user_id}` : 'Unknown') }}
                        </td>
                        <td class="px-3 py-2 text-xs">
                          <div class="flex flex-wrap gap-2">
                            <button
                              type="button"
                              class="font-medium text-indigo-600 hover:text-indigo-800"
                              @click="openRecordDetail(record)"
                            >
                              Record Detail
                            </button>
                            <button
                              type="button"
                              class="font-medium text-slate-600 hover:text-slate-800"
                              @click="openSessionRecords(record)"
                            >
                              Session
                            </button>
                            <a
                              v-if="record.record_link"
                              :href="record.record_link"
                              target="_blank"
                              rel="noopener noreferrer"
                              class="font-medium text-emerald-700 hover:text-emerald-800"
                            >
                              Zenodo
                            </a>
                            <button
                              v-if="record.can_create_version"
                              type="button"
                              class="font-medium text-indigo-700 hover:text-indigo-900 disabled:opacity-50"
                              :disabled="versioningRecordKey === `${record.session_id}-${record.local_record_id}`"
                              @click="createVersionDraft(record)"
                            >
                              {{ versioningRecordKey === `${record.session_id}-${record.local_record_id}` ? 'Creating Version...' : 'Create Version Draft' }}
                            </button>
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div v-else-if="activeTab === 'drafts'" class="p-4">
              <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Complete Drafts</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.draft_breakdown?.complete_draft || 0 }}</p>
                </div>
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Partial Drafts</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.draft_breakdown?.partial_draft || 0 }}</p>
                </div>
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Prepared Only</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.draft_breakdown?.prepared_only || 0 }}</p>
                </div>
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Repair Version Drafts</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ summary.draft_breakdown?.repair_version_draft || 0 }}</p>
                </div>
              </div>
            </div>

            <div v-else class="space-y-4 p-4">
              <div class="flex flex-wrap gap-2">
                <button
                  type="button"
                  class="rounded-lg border border-indigo-200 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
                  :disabled="exporting"
                  @click="downloadExport('primary_json')"
                >
                  Download Primary JSON
                </button>
                <button
                  type="button"
                  class="rounded-lg border border-indigo-200 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
                  :disabled="exporting"
                  @click="downloadExport('primary_csv')"
                >
                  Download Primary CSV
                </button>
                <button
                  type="button"
                  class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  :disabled="exporting"
                  @click="downloadExport('secondary_json')"
                >
                  Download Superseded / Draft JSON
                </button>
                <button
                  type="button"
                  class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  :disabled="exporting"
                  @click="downloadExport('secondary_csv')"
                >
                  Download Superseded / Draft CSV
                </button>
              </div>

              <div v-if="exportBundle" class="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Primary Records</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ exportBundle.primary_record_count || 0 }}</p>
                </div>
                <div class="rounded-xl border border-slate-200 p-4">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Superseded / Draft Records</p>
                  <p class="mt-2 text-2xl font-bold text-slate-900">{{ exportBundle.secondary_record_count || 0 }}</p>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Alert from '@/components/ui/Alert.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useToast } from '@/composables/useToast'
import datasetService from '@/services/dataset.service.js'
import submissionService from '@/services/submission.service.js'
import { buildDatasetRoute } from '@/utils/datasetKey.js'

const VALID_TABS = new Set(['overview', 'duplicates', 'drafts', 'exports'])
const VALID_ENVIRONMENTS = new Set(['production', 'sandbox', 'all'])

const route = useRoute()
const router = useRouter()
const toast = useToast()
const authStore = useAuthStore()

const loading = ref(true)
const reviewLoading = ref(false)
const exporting = ref(false)
const error = ref('')
const datasets = ref([])
const summary = ref({})
const duplicates = ref([])
const globalConflictReview = ref([])
const globalConflictReviewCount = ref(0)
const exportBundle = ref(null)
const authoritativeSessionInsight = ref(null)
const authoritativeSessionInsightError = ref('')
const activeTab = ref('overview')
const selectedAuthoritativeSessionId = ref(null)
const selectedEnvironment = ref('production')
const selectedDatasetKey = ref('')
const selectedPathFilter = ref('')
const pathFilterDraft = ref('')
const versioningRecordKey = ref('')

const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'duplicates', label: 'Duplicates' },
  { id: 'drafts', label: 'Drafts / Repairs' },
  { id: 'exports', label: 'Exports' },
]

const showError = computed(() => !!error.value)
const isPrivileged = computed(() => ['admin', 'moderator'].includes(authStore.user?.role || ''))

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const formatDraftBreakdown = (value = {}) => {
  const items = Object.entries(value || {})
  if (!items.length) return 'No draft-like rows'
  return items.map(([key, count]) => `${key}: ${count}`).join(' · ')
}

const triggerDownload = (content, filename, mimeType) => {
  if (!content) return
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const applyRouteState = () => {
  selectedDatasetKey.value = route.params.datasetKey ? decodeURIComponent(String(route.params.datasetKey)) : ''
  const routeTab = String(route.query.tab || 'overview')
  activeTab.value = VALID_TABS.has(routeTab) ? routeTab : 'overview'
  const routeEnvironment = String(route.query.environment || 'production')
  selectedEnvironment.value = VALID_ENVIRONMENTS.has(routeEnvironment) ? routeEnvironment : 'production'
  selectedPathFilter.value = route.query.path ? decodeURIComponent(String(route.query.path)) : ''
  pathFilterDraft.value = selectedPathFilter.value
}

const buildWorkspaceLocation = (overrides = {}) => {
  const datasetKey = Object.prototype.hasOwnProperty.call(overrides, 'datasetKey')
    ? overrides.datasetKey
    : selectedDatasetKey.value
  const tab = Object.prototype.hasOwnProperty.call(overrides, 'tab')
    ? overrides.tab
    : activeTab.value
  const environment = Object.prototype.hasOwnProperty.call(overrides, 'environment')
    ? overrides.environment
    : selectedEnvironment.value
  const path = Object.prototype.hasOwnProperty.call(overrides, 'path')
    ? overrides.path
    : selectedPathFilter.value

  const query = {}
  if (tab && tab !== 'overview') query.tab = tab
  if (environment && environment !== 'production') query.environment = environment
  if (path) query.path = path

  return {
    name: 'DatasetIntegrityWorkspace',
    params: { datasetKey: datasetKey || undefined },
    query,
  }
}

const syncWorkspaceRoute = async (overrides = {}) => {
  const target = buildWorkspaceLocation(overrides)
  const resolved = router.resolve(target)
  if (resolved.fullPath !== route.fullPath) {
    await router.replace(target)
  }
}

const loadDatasets = async () => {
  const response = await datasetService.listDatasets({ environment: selectedEnvironment.value })
  datasets.value = response.data?.datasets || []
}

const loadConflictReview = async () => {
  if (!isPrivileged.value || selectedDatasetKey.value) {
    globalConflictReview.value = []
    globalConflictReviewCount.value = 0
    return
  }
  reviewLoading.value = true
  try {
    const response = await datasetService.getConflictReview({
      environment: selectedEnvironment.value,
      limit: 25,
      group_limit: 3,
    })
    globalConflictReview.value = response.data?.datasets || []
    globalConflictReviewCount.value = Number(response.data?.duplicate_group_count || 0)
  } finally {
    reviewLoading.value = false
  }
}

const loadDatasetDetail = async () => {
  if (!selectedDatasetKey.value) {
    summary.value = {}
    duplicates.value = []
    exportBundle.value = null
    authoritativeSessionInsight.value = null
    authoritativeSessionInsightError.value = ''
    return
  }
  const params = { environment: selectedEnvironment.value }
  if (selectedPathFilter.value) {
    params.path = selectedPathFilter.value
  }
  const [summaryResponse, duplicatesResponse] = await Promise.all([
    datasetService.getDatasetSummary(selectedDatasetKey.value, { environment: selectedEnvironment.value }),
    datasetService.getDatasetDuplicates(selectedDatasetKey.value, params),
  ])
  summary.value = summaryResponse.data || {}
  duplicates.value = duplicatesResponse.data?.groups || []
  selectedAuthoritativeSessionId.value = summary.value.authoritative_session_id || null
  selectedPathFilter.value = duplicatesResponse.data?.path_filter || selectedPathFilter.value || ''
  pathFilterDraft.value = selectedPathFilter.value
  exportBundle.value = null
  await loadAuthoritativeSessionInsight(selectedAuthoritativeSessionId.value)
}

const loadAuthoritativeSessionInsight = async (sessionId = selectedAuthoritativeSessionId.value) => {
  authoritativeSessionInsight.value = null
  authoritativeSessionInsightError.value = ''
  if (!selectedDatasetKey.value || !sessionId) {
    return
  }

  try {
    const response = await submissionService.getSessionWorkspaceSummary(sessionId)
    authoritativeSessionInsight.value = response.data || null
  } catch (err) {
    console.error('Failed to load authoritative session intelligence:', err)
    authoritativeSessionInsightError.value =
      err.error?.message || err.error || err.message || 'Workspace intelligence is currently unavailable.'
  }
}

const loadCurrent = async () => {
  loading.value = true
  error.value = ''
  try {
    await loadDatasets()
    if (selectedDatasetKey.value) {
      await loadDatasetDetail()
      globalConflictReview.value = []
      globalConflictReviewCount.value = 0
    } else {
      summary.value = {}
      duplicates.value = []
      exportBundle.value = null
      await loadConflictReview()
    }
  } catch (err) {
    console.error('Failed to load dataset workspace:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load dataset workspace.'
  } finally {
    loading.value = false
  }
}

const navigateToDataset = async () => {
  await syncWorkspaceRoute({
    datasetKey: selectedDatasetKey.value || undefined,
    path: undefined,
  })
}

const ensureExportBundle = async () => {
  if (exportBundle.value || !selectedDatasetKey.value) return
  exporting.value = true
  try {
    const response = await datasetService.exportDataset(selectedDatasetKey.value, {
      format: 'bundle',
      environment: selectedEnvironment.value,
      authoritative_session_id: selectedAuthoritativeSessionId.value || undefined,
    })
    exportBundle.value = response.data || {}
  } finally {
    exporting.value = false
  }
}

const downloadExport = async (kind) => {
  try {
    await ensureExportBundle()
    const datasetKey = selectedDatasetKey.value || 'dataset'
    if (kind === 'primary_json') {
      triggerDownload(
        JSON.stringify(exportBundle.value?.primary_json || {}, null, 2),
        `${datasetKey}.json`,
        'application/json'
      )
      return
    }
    if (kind === 'secondary_json') {
      triggerDownload(
        JSON.stringify(exportBundle.value?.secondary_json || {}, null, 2),
        `${datasetKey}_superseded_drafts.json`,
        'application/json'
      )
      return
    }
    if (kind === 'primary_csv') {
      triggerDownload(exportBundle.value?.primary_csv || '', `${datasetKey}.csv`, 'text/csv')
      return
    }
    if (kind === 'secondary_csv') {
      triggerDownload(exportBundle.value?.secondary_csv || '', `${datasetKey}_superseded_drafts.csv`, 'text/csv')
    }
  } catch (err) {
    console.error('Failed to export dataset:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to export dataset.'
  }
}

const applyPathFilter = async () => {
  activeTab.value = 'duplicates'
  await syncWorkspaceRoute({
    tab: 'duplicates',
    path: pathFilterDraft.value.trim() || undefined,
  })
}

const clearPathFilter = async () => {
  pathFilterDraft.value = ''
  await syncWorkspaceRoute({ path: undefined, tab: 'duplicates' })
}

const focusDuplicateGroup = async (normalizedSourcePath) => {
  pathFilterDraft.value = normalizedSourcePath || ''
  activeTab.value = 'duplicates'
  await syncWorkspaceRoute({
    tab: 'duplicates',
    path: normalizedSourcePath || undefined,
  })
}

const openRecordDetail = (record) => {
  router.push({
    name: 'SessionRecordDetail',
    params: {
      sessionId: String(record.session_id),
      recordId: String(record.local_record_id),
    },
  })
}

const openSessionRecords = (record) => {
  router.push({
    name: 'SessionRecords',
    params: { sessionId: String(record.session_id) },
  })
}

const createVersionDraft = async (record) => {
  if (!record?.session_id || !record?.local_record_id) return
  if (!window.confirm(`Create a new Zenodo version draft for "${record.record_title || 'this record'}" using the complete local file set?`)) {
    return
  }

  const key = `${record.session_id}-${record.local_record_id}`
  versioningRecordKey.value = key
  try {
    const response = await submissionService.createSessionRecordVersion(record.session_id, record.local_record_id, { publish: false })
    const newLocalRecordId = response.data?.new_version?.new_local_record_id
    toast.success(newLocalRecordId ? `New version draft created as local record #${newLocalRecordId}` : 'New version draft created')
    await loadCurrent()
    if (newLocalRecordId) {
      router.push({
        name: 'SessionRecordDetail',
        params: {
          sessionId: String(record.session_id),
          recordId: String(newLocalRecordId),
        },
      })
    }
  } catch (err) {
    console.error('Failed to create new version:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to create new Zenodo version')
  } finally {
    versioningRecordKey.value = ''
  }
}

watch(
  () => [route.params.datasetKey || '', route.query.environment || '', route.query.path || ''].join('|'),
  () => {
    applyRouteState()
    loadCurrent()
  }
)

watch(
  () => route.query.tab,
  async () => {
    applyRouteState()
    if (activeTab.value === 'exports' && selectedDatasetKey.value) {
      await ensureExportBundle()
    }
  }
)

watch(selectedAuthoritativeSessionId, () => {
  exportBundle.value = null
  if (!loading.value) {
    loadAuthoritativeSessionInsight(selectedAuthoritativeSessionId.value)
  }
})

watch(selectedEnvironment, async (nextValue, previousValue) => {
  if (nextValue === previousValue) return
  exportBundle.value = null
  await syncWorkspaceRoute({ environment: nextValue })
})

watch(activeTab, async (nextValue, previousValue) => {
  if (nextValue === previousValue) return
  await syncWorkspaceRoute({ tab: nextValue })
  if (nextValue === 'exports' && selectedDatasetKey.value) {
    await ensureExportBundle()
  }
})

onMounted(() => {
  applyRouteState()
  loadCurrent()
})
</script>
