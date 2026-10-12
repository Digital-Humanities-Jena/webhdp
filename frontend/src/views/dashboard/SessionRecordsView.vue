<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 via-white to-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button
            type="button"
            class="text-sm font-medium text-indigo-600 hover:text-indigo-800"
            @click="goBack"
          >
            &larr; Back
          </button>
          <h1 class="mt-2 text-3xl font-bold text-slate-900">Session Zenodo Records</h1>
          <p class="mt-1 text-sm text-slate-600">
            Session #{{ route.params.sessionId }}
            <span v-if="payload?.session?.status" class="ml-2 text-xs uppercase tracking-wide text-slate-500">
              {{ payload.session.status }}
            </span>
          </p>
          <div v-if="payload?.session" class="mt-3 flex flex-wrap gap-2">
            <span
              v-if="payload.session.access_mode === 'explorer_only'"
              class="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-rose-700"
            >
              Explorer-only
            </span>
            <span
              v-if="payload.session.origin_type === 'hdpc_import'"
              class="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-sky-700"
            >
              Imported .hdpc
            </span>
            <span
              v-if="payload.session.origin_type === 'zenodo_deep_retrieval'"
              class="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-indigo-700"
            >
              Zenodo retrieval
            </span>
          </div>
          <p
            v-if="payload?.session?.access_mode === 'explorer_only'"
            class="mt-2 text-xs font-medium text-rose-700"
          >
            {{ explorerOnlyNotice }}
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            v-if="payload?.session?.permissions?.can_manage"
            type="button"
            class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
            @click="governanceOpen = true"
          >
            Manage Session
          </button>
          <router-link
            v-if="datasetWorkspaceRoute"
            :to="datasetWorkspaceRoute"
            class="px-3 py-2 text-sm font-medium border border-emerald-200 rounded-lg text-emerald-700 hover:bg-emerald-50"
          >
            Dataset Workspace
          </router-link>
          <router-link
            :to="`/sessions/${route.params.sessionId}/provenance-report`"
            class="px-3 py-2 text-sm font-medium border border-emerald-200 rounded-lg text-emerald-700 hover:bg-emerald-50"
          >
            Provenance Report
          </router-link>
          <router-link
            to="/records/explorer"
            class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
          >
            Cross-Session Explorer
          </router-link>
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
            @click="copyZenodoIds"
            :disabled="records.length === 0"
          >
            Copy Zenodo IDs
          </button>
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-indigo-200 rounded-lg text-indigo-700 hover:bg-indigo-50"
            @click="downloadJson"
            :disabled="!payload"
          >
            Export JSON
          </button>
          <button
            v-if="canDownloadSharedHdpc"
            type="button"
            class="px-3 py-2 text-sm font-medium border border-emerald-200 rounded-lg text-emerald-700 hover:bg-emerald-50 disabled:opacity-60 disabled:cursor-not-allowed"
            data-testid="session-records-download-shared-hdpc"
            @click="handleDownloadSharedHdpc"
            :disabled="downloadingHdpc"
            :title="payload.session.shared_hdpc_download_policy?.message || 'Download sanitized shared .hdpc export'"
          >
            {{ downloadingHdpc === 'shared' ? 'Downloading...' : 'Shared .hdpc' }}
          </button>
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-indigo-200 rounded-lg text-indigo-700 hover:bg-indigo-50 disabled:opacity-60 disabled:cursor-not-allowed"
            data-testid="session-records-download-hdpc"
            @click="handleDownloadHdpc"
            :disabled="!canDownloadHdpc || !!downloadingHdpc"
            :title="canDownloadHdpc ? 'Download raw session .hdpc' : payload?.session?.hdpc_download_policy?.message || 'Raw .hdpc download is unavailable'"
          >
            {{ downloadingHdpc === 'raw' ? 'Downloading...' : 'Download .hdpc' }}
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Loading session records..." />

      <div v-else-if="error" class="bg-white shadow rounded-xl p-6">
        <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
      </div>

      <div v-else-if="payload" class="space-y-6">
        <details v-if="payload.recent_runs?.length" class="rounded-xl border border-slate-200 bg-white p-4">
          <summary class="cursor-pointer text-sm font-semibold text-slate-800">Recent processing runs</summary>
          <ul class="mt-2 space-y-1 text-sm"><li v-for="run in payload.recent_runs" :key="run.run_id"><RouterLink :to="`/runs/${run.run_id}`" class="inline-flex min-h-11 items-center text-indigo-700 underline">{{ formatDate(run.started_at) }} · {{ run.status }}</RouterLink></li></ul>
        </details>
        <div v-if="warnings.length > 0" class="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl p-4">
          <p class="text-sm font-semibold">Data availability warning</p>
          <p class="text-sm mt-1">{{ warnings[0] }}</p>
        </div>

        <div v-if="workspaceSummary" class="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <section class="xl:col-span-2 bg-white rounded-xl border border-slate-200 p-4">
            <div class="flex items-start justify-between gap-4">
              <div>
                <h2 class="text-sm font-semibold text-slate-800">Workspace Intelligence</h2>
                <p class="mt-1 text-sm text-slate-500">
                  Consolidated local `.hdpc` state, upload readiness, and versioning hints for this session.
                </p>
              </div>
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-50 border border-slate-200 rounded-lg hover:bg-slate-100"
                @click="refreshMergedData"
                :disabled="batchPolling"
              >
                Refresh Intelligence
              </button>
            </div>

            <div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
              <div>
                <p class="text-slate-500">Project</p>
                <p class="font-medium text-slate-800">{{ workspaceSummary.project_info?.project_name || 'Unnamed project' }}</p>
              </div>
              <div>
                <p class="text-slate-500">Batch entity</p>
                <p class="font-medium text-slate-800">{{ workspaceSummary.configuration_hints?.batch_entity || 'n/a' }}</p>
              </div>
              <div>
                <p class="text-slate-500">Published latest</p>
                <p class="font-medium text-slate-800">
                  {{ workspaceSummary.versioning_summary?.latest_published_record?.record_title || 'No published record yet' }}
                </p>
              </div>
            </div>

            <div class="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
              <div class="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p class="text-xs uppercase tracking-wide text-slate-500">Uploadable</p>
                <p class="mt-1 text-xl font-bold text-slate-900">{{ workspaceSummary.upload_summary?.uploadable_item_count || 0 }}</p>
              </div>
              <div class="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p class="text-xs uppercase tracking-wide text-amber-700">Prepared</p>
                <p class="mt-1 text-xl font-bold text-amber-800">{{ workspaceSummary.record_summary?.prepared_count || 0 }}</p>
              </div>
              <div class="rounded-lg border border-sky-200 bg-sky-50 p-3">
                <p class="text-xs uppercase tracking-wide text-sky-700">Draft</p>
                <p class="mt-1 text-xl font-bold text-sky-800">{{ workspaceSummary.record_summary?.draft_count || 0 }}</p>
              </div>
              <div class="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                <p class="text-xs uppercase tracking-wide text-emerald-700">Published</p>
                <p class="mt-1 text-xl font-bold text-emerald-800">{{ workspaceSummary.record_summary?.published_count || 0 }}</p>
              </div>
            </div>
          </section>

          <section class="bg-white rounded-xl border border-slate-200 p-4">
            <h2 class="text-sm font-semibold text-slate-800">Session Batch Actions</h2>
            <p class="mt-1 text-sm text-slate-500">
              Run typed native operations on the eligible local records and files in this session.
            </p>

            <div v-if="batchTaskStatus" class="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm">
              <p class="font-semibold text-indigo-900">{{ batchTaskStatus.status || 'Queued' }}</p>
              <p class="mt-1 text-indigo-800">
                {{ batchTaskStatus.progress?.processed || 0 }} / {{ batchTaskStatus.progress?.total_items || 0 }}
                processed · {{ batchTaskStatus.progress?.completed || 0 }} completed ·
                {{ batchTaskStatus.progress?.failed || 0 }} failed
              </p>
            </div>

            <div class="mt-4 space-y-3">
              <div
                v-for="operation in batchOperationCards"
                :key="operation.id"
                class="rounded-lg border border-slate-200 p-3"
              >
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-slate-900">{{ operation.label }}</p>
                    <p class="mt-1 text-xs text-slate-500">{{ operation.description }}</p>
                    <p class="mt-2 text-xs font-medium text-slate-700">{{ operation.count }} eligible</p>
                  </div>
                  <button
                    type="button"
                    class="px-3 py-1.5 text-xs font-semibold rounded-lg border border-indigo-200 text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :disabled="operation.count === 0 || batchLaunching || sessionIsExplorerOnly"
                    @click="launchBatchOperation(operation.id)"
                  >
                    {{ batchLaunching === operation.id ? 'Queueing…' : 'Run' }}
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Source Items</p>
            <p class="text-2xl font-bold text-slate-900">{{ summary.total_records || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-indigo-200 p-4">
            <p class="text-xs uppercase tracking-wide text-indigo-600">Processed</p>
            <p class="text-2xl font-bold text-indigo-700">{{ summary.processed_records || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Available Only</p>
            <p class="text-2xl font-bold text-slate-900">{{ summary.available_not_selected_records || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-emerald-200 p-4">
            <p class="text-xs uppercase tracking-wide text-emerald-600">Published</p>
            <p class="text-2xl font-bold text-emerald-700">{{ summary.published_records || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-amber-200 p-4">
            <p class="text-xs uppercase tracking-wide text-amber-600">Drafts</p>
            <p class="text-2xl font-bold text-amber-700">{{ summary.draft_records || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-rose-200 p-4">
            <p class="text-xs uppercase tracking-wide text-rose-600">With Warnings</p>
            <p class="text-2xl font-bold text-rose-700">{{ summary.records_with_warnings || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-sky-200 p-4">
            <p class="text-xs uppercase tracking-wide text-sky-600">Session Files</p>
            <p class="text-2xl font-bold text-sky-700">{{ summary.session_file_count || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-rose-200 p-4">
            <p class="text-xs uppercase tracking-wide text-rose-600">Missing Thumbnails</p>
            <p class="text-2xl font-bold text-rose-700">{{ summary.records_missing_uploaded_thumbnails || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-emerald-200 p-4">
            <p class="text-xs uppercase tracking-wide text-emerald-600">Repairable</p>
            <p class="text-2xl font-bold text-emerald-700">{{ summary.repairable_thumbnail_records || 0 }}</p>
          </div>
        </div>

        <div
          v-if="summary.hidden_duplicate_records"
          class="bg-indigo-50 border border-indigo-200 text-indigo-900 rounded-xl p-4 text-sm"
        >
          {{ summary.hidden_duplicate_records }} lower-priority prepared record{{ summary.hidden_duplicate_records === 1 ? '' : 's' }}
          were hidden in this session view because a newer draft or processed row already represents the same source file here.
          <span v-if="datasetWorkspaceRoute" class="block mt-1">
            Use the dataset workspace for authoritative cross-session duplicate and completion status.
          </span>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <h2 class="text-sm font-semibold text-slate-800">Provenance Overview</h2>
          <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div>
              <p class="text-slate-500">MSF path</p>
              <p class="font-medium text-slate-800 break-all">{{ provenance.msf_path || 'Not set' }}</p>
            </div>
            <div>
              <p class="text-slate-500">LOD mapping fields</p>
              <p class="font-medium text-slate-800">{{ provenance.mapping_field_count || 0 }}</p>
            </div>
            <div>
              <p class="text-slate-500">Files with batch metadata</p>
              <p class="font-medium text-slate-800">{{ provenance.batch_metadata_file_count || 0 }}</p>
            </div>
          </div>
          <div v-if="provenance.mapping_fields?.length" class="mt-3 flex flex-wrap gap-2">
            <span
              v-for="field in provenance.mapping_fields.slice(0, 12)"
              :key="field"
              class="px-2 py-1 text-xs rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100"
            >
              {{ field }}
            </span>
            <span
              v-if="provenance.mapping_fields.length > 12"
              class="px-2 py-1 text-xs rounded-full bg-slate-100 text-slate-600"
            >
              +{{ provenance.mapping_fields.length - 12 }} more
            </span>
          </div>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
            <input
              v-model="searchTerm"
              type="text"
              placeholder="Search title, DOI, record ID..."
              class="px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-200"
            />
            <select
              v-model="statusFilter"
              class="px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
            >
              <option value="all">All statuses</option>
              <option value="published">Published</option>
              <option value="draft">Draft</option>
              <option value="other">Other</option>
            </select>
            <select
              v-model="sortBy"
              class="px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
            >
              <option value="updated_desc">Newest first</option>
              <option value="updated_asc">Oldest first</option>
              <option value="title_asc">Title A-Z</option>
              <option value="title_desc">Title Z-A</option>
            </select>
            <label class="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-300 text-sm text-slate-700">
              <input v-model="onlyMapped" type="checkbox" class="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
              Only mapped metadata
            </label>
          </div>
        </div>

        <div v-if="filteredRecords.length === 0" class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500">
          No records match your current filters.
        </div>

        <div v-else class="space-y-4">
          <article
            v-for="record in filteredRecords"
            :key="record.local_record_id"
            class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
          >
            <div class="p-5 border-b border-slate-100">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 class="text-lg font-semibold text-slate-900">{{ record.record_title || 'Untitled record' }}</h3>
                  <p class="mt-1 text-xs text-slate-500">
                    Local ID {{ record.local_record_id }}
                    <span v-if="record.updated_at">• Updated {{ formatDate(record.updated_at) }}</span>
                  </p>
                  <router-link
                    :to="`/sessions/${route.params.sessionId}/records/${record.local_record_id}`"
                    class="inline-block mt-2 text-xs font-semibold text-indigo-700 hover:text-indigo-900"
                  >
                    Open Record Detail
                  </router-link>
                </div>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-if="record.processed_in_latest_submission"
                    class="px-2.5 py-1 text-xs font-semibold rounded-full border bg-indigo-50 text-indigo-700 border-indigo-200"
                  >
                    Processed in latest submission
                  </span>
                  <span
                    v-else-if="record.available_not_selected"
                    class="px-2.5 py-1 text-xs font-semibold rounded-full border bg-slate-50 text-slate-700 border-slate-200"
                  >
                    Available but not selected
                  </span>
                  <span
                    v-else-if="record.selected_for_submission"
                    class="px-2.5 py-1 text-xs font-semibold rounded-full border bg-sky-50 text-sky-700 border-sky-200"
                  >
                    Selected for workflow
                  </span>
                  <span :class="statusClass(record.record_status)" class="px-2.5 py-1 text-xs font-semibold rounded-full border">
                    {{ record.record_status || 'unknown' }}
                  </span>
                  <span
                    class="px-2.5 py-1 text-xs font-semibold rounded-full border"
                    :class="record.is_sandbox === true
                      ? 'bg-orange-50 text-orange-700 border-orange-200'
                      : record.is_sandbox === false
                        ? 'bg-cyan-50 text-cyan-700 border-cyan-200'
                        : 'bg-slate-50 text-slate-700 border-slate-200'"
                  >
                    {{
                      record.is_sandbox === true
                        ? 'Sandbox'
                        : record.is_sandbox === false
                        ? 'Production'
                        : 'Unknown env'
                    }}
                  </span>
                  <span
                    v-if="record.thumbnail_health?.missing_uploaded_thumbnails"
                    class="px-2.5 py-1 text-xs font-semibold rounded-full border bg-rose-50 text-rose-700 border-rose-200"
                  >
                    Missing uploaded thumbnails
                  </span>
                </div>
              </div>

              <div class="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 text-sm">
                <div>
                  <p class="text-slate-500">Zenodo record ID</p>
                  <p class="font-medium text-slate-800">{{ record.zenodo_record_id || 'N/A' }}</p>
                </div>
                <div>
                  <p class="text-slate-500">Concept record ID</p>
                  <p class="font-medium text-slate-800">{{ record.concept_rec_id || 'N/A' }}</p>
                </div>
                <div>
                  <p class="text-slate-500">DOI</p>
                  <p class="font-medium text-slate-800 break-all">{{ record.zenodo_doi || 'N/A' }}</p>
                </div>
                <div class="flex items-end gap-2">
                  <a
                    v-if="record.record_link"
                    :href="record.record_link"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-lg hover:bg-indigo-100"
                  >
                    Open Record
                  </a>
                  <button
                    v-if="record.thumbnail_health?.can_repair_missing_thumbnails"
                    type="button"
                    class="inline-flex px-3 py-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 disabled:opacity-60 disabled:cursor-not-allowed"
                    :disabled="versioningRecordId === record.local_record_id"
                    @click="createVersion(record)"
                  >
                    {{ versioningRecordId === record.local_record_id ? 'Creating…' : 'Repair via New Version' }}
                  </button>
                  <a
                    v-if="record.draft_link && record.draft_link !== record.record_link"
                    :href="record.draft_link"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-50 border border-slate-200 rounded-lg hover:bg-slate-100"
                  >
                    Open Draft API
                  </a>
                </div>
              </div>
            </div>

            <div class="p-5 grid grid-cols-1 xl:grid-cols-3 gap-5">
              <section class="xl:col-span-2">
                <h4 class="text-sm font-semibold text-slate-800">Included Files ({{ record.file_count || 0 }})</h4>
                <div v-if="!record.files?.length" class="mt-2 text-sm text-slate-500">No files linked in record map.</div>
                <ul v-else class="mt-2 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
                  <li v-for="file in record.files" :key="`${record.local_record_id}-${file.file_id}-${file.filename}`" class="p-3 bg-white">
                    <div class="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p class="text-sm font-medium text-slate-900">{{ file.filename || file.mapped_file_path }}</p>
                        <p class="text-xs text-slate-500 break-all">{{ file.absolute_path || file.mapped_file_path || 'N/A' }}</p>
                        <p class="mt-1 text-xs text-slate-500">
                          {{ file.file_purpose || 'unknown purpose' }}
                          <span v-if="file.file_type">• {{ file.file_type }}</span>
                          <span v-if="file.size_bytes">• {{ formatBytes(file.size_bytes) }}</span>
                        </p>
                      </div>
                      <div class="text-right text-xs text-slate-500">
                        <p>{{ recordFileStatusLabel(file.upload_status || file.status || 'pending') }}</p>
                        <p v-if="file.pipeline_source || file.step_source" class="mt-1">
                          {{ file.pipeline_source || 'unknown' }} / {{ file.step_source || 'unknown' }}
                        </p>
                      </div>
                    </div>
                  </li>
                </ul>
              </section>

              <section>
                <h4 class="text-sm font-semibold text-slate-800">Data Provenance</h4>
                <div class="mt-2 space-y-2 text-sm">
                  <p class="text-slate-600">
                    <span class="font-medium text-slate-800">MSF:</span>
                    <span class="break-all">{{ record.provenance?.msf_path || provenance.msf_path || 'Not set' }}</span>
                  </p>
                  <p class="text-slate-600">
                    <span class="font-medium text-slate-800">Mapped from:</span>
                    {{ record.provenance?.mapped_from_filename || 'Not matched' }}
                  </p>
                  <p class="text-slate-600">
                    <span class="font-medium text-slate-800">Mapped fields:</span>
                    {{ record.provenance?.mapping_field_count || 0 }}
                  </p>
                </div>

                <div v-if="record.provenance?.pipeline_lineage?.length" class="mt-3 flex flex-wrap gap-2">
                  <span
                    v-for="lineage in record.provenance.pipeline_lineage"
                    :key="`${record.local_record_id}-${lineage.pipeline}-${lineage.step}`"
                    class="px-2 py-1 text-xs rounded-full bg-slate-100 text-slate-700 border border-slate-200"
                  >
                    {{ lineage.pipeline }} / {{ lineage.step }}
                  </span>
                </div>

                <details v-if="record.provenance?.mapped_metadata_keys?.length" class="mt-3">
                  <summary class="cursor-pointer text-xs font-semibold text-indigo-700">Show mapped metadata</summary>
                  <pre class="mt-2 p-2 text-xs bg-slate-50 rounded-lg border border-slate-200 overflow-auto max-h-44">{{ formatJson(record.provenance.mapped_metadata) }}</pre>
                </details>

                <div class="mt-4">
                  <h5 class="text-xs font-semibold uppercase tracking-wide text-slate-500">Pipeline Status</h5>
                  <ul class="mt-2 space-y-1 text-xs text-slate-700">
                    <li>Render: {{ record.processing?.render_status || 'n/a' }}</li>
                    <li>USDZ: {{ record.processing?.usdz_status || 'n/a' }}</li>
                    <li>EDM: {{ record.processing?.edm_status || 'n/a' }}</li>
                    <li>IIIF: {{ record.processing?.iiif_status || 'n/a' }}</li>
                    <li>METS: {{ record.processing?.mets_status || 'n/a' }}</li>
                    <li v-if="record.thumbnail_health?.is_3d_record">
                      Uploaded thumbnails: {{ record.thumbnail_health?.uploaded_thumbnail_count || 0 }}
                    </li>
                    <li v-if="record.thumbnail_health?.is_3d_record">
                      Local rendered thumbnails: {{ record.thumbnail_health?.local_rendered_thumbnail_count || 0 }}
                    </li>
                  </ul>
                  <p v-if="record.processing?.error" class="mt-2 text-xs text-rose-700">Error: {{ record.processing.error }}</p>
                  <p v-else-if="record.processing?.warnings?.length" class="mt-2 text-xs text-amber-700">
                    {{ record.processing.warnings[0] }}
                  </p>
                </div>
              </section>
            </div>
          </article>
        </div>
      </div>
    </div>
    <SessionGovernanceDrawer
      :open="governanceOpen"
      :session="payload?.session || null"
      @close="governanceOpen = false"
      @updated="handleGovernanceUpdated"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import submissionService from '@/services/submission.service.js'
import fileService from '@/services/file.service.js'
import SessionGovernanceDrawer from '@/components/dashboard/SessionGovernanceDrawer.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { useToast } from '@/composables/useToast'
import { recordFileStatusLabel } from '@/utils/workflowState'
import { buildDatasetRoute } from '@/utils/datasetKey.js'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const loading = ref(true)
const payload = ref(null)
const workspaceSummary = ref(null)
const batchTasks = ref([])
const batchTaskStatus = ref(null)
const activeBatchTaskId = ref('')
const error = ref('')
const versioningRecordId = ref(null)
const batchLaunching = ref('')
const batchPolling = ref(false)
const governanceOpen = ref(false)
const downloadingHdpc = ref('')
let batchPollTimer = null
const showError = computed(() => !!error.value)

const searchTerm = ref('')
const statusFilter = ref('all')
const sortBy = ref('updated_desc')
const onlyMapped = ref(false)

const records = computed(() => payload.value?.records || [])
const summary = computed(() => payload.value?.summary || {})
const provenance = computed(() => payload.value?.provenance || {})
const warnings = computed(() => payload.value?.warnings || [])
const sessionIsExplorerOnly = computed(() => payload.value?.session?.access_mode === 'explorer_only')
const canDownloadHdpc = computed(() => Boolean(payload.value?.session?.permissions?.can_download_hdpc))
const canDownloadSharedHdpc = computed(() => Boolean(payload.value?.session?.permissions?.can_download_shared_hdpc))
const explorerOnlyNotice = computed(() => {
  if (payload.value?.session?.origin_type === 'zenodo_deep_retrieval') {
    return 'This session was generated by a Zenodo account retrieval. Record views remain available, but workflow and publishing actions are read-only.'
  }
  return 'This session came from a sanitized shared export. Record views remain available, but workflow and publishing actions are read-only.'
})
const operationsSummary = computed(() => workspaceSummary.value?.operations || {})
const batchOperationCards = computed(() => {
  const actionable = operationsSummary.value?.actionable_operations || {}
  return [
    { id: 'create_drafts', label: 'Create Drafts', description: 'Create Zenodo drafts for prepared local records.', count: actionable.create_drafts?.count || 0 },
    { id: 'discard_drafts', label: 'Discard Drafts', description: 'Rollback active drafts to their prepared local state.', count: actionable.discard_drafts?.count || 0 },
    { id: 'upload_files', label: 'Upload Files', description: 'Upload pending record files for active drafts.', count: actionable.upload_files?.count || 0 },
    { id: 'publish_records', label: 'Publish Records', description: 'Publish drafts whose files are already uploaded.', count: actionable.publish_records?.count || 0 },
    { id: 'remove_files', label: 'Remove Files', description: 'Safely remove local-only source files that are still pending preparation.', count: actionable.remove_files?.count || 0 },
  ]
})
const datasetKey = computed(() => {
  return provenance.value?.dataset_key
    || records.value.find((record) => record?.dataset_key)?.dataset_key
    || records.value.find((record) => record?.provenance?.dataset_key)?.provenance?.dataset_key
    || ''
})
const datasetWorkspaceRoute = computed(() => {
  if (!datasetKey.value) return ''
  const environments = new Set(records.value.filter(record => typeof record.is_sandbox === 'boolean').map(record => record.is_sandbox ? 'sandbox' : 'production'))
  const environment = environments.size > 1 ? 'all' : [...environments][0] || payload.value?.session?.default_zenodo_environment || 'production'
  return buildDatasetRoute(datasetKey.value, { environment })
})

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return Number.isNaN(date.getTime()) ? String(dateString) : date.toLocaleString()
}

const formatBytes = (bytes) => {
  if (!bytes || Number.isNaN(Number(bytes))) return 'N/A'
  const value = Number(bytes)
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

const formatJson = (value) => {
  try {
    return JSON.stringify(value || {}, null, 2)
  } catch {
    return String(value)
  }
}

const statusClass = (status) => {
  if (status === 'published') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (status === 'draft') return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-slate-50 text-slate-700 border-slate-200'
}

const filteredRecords = computed(() => {
  const term = searchTerm.value.trim().toLowerCase()

  let list = records.value.filter((record) => {
    if (statusFilter.value === 'published' && record.record_status !== 'published') return false
    if (statusFilter.value === 'draft' && record.record_status !== 'draft') return false
    if (statusFilter.value === 'other' && ['published', 'draft'].includes(record.record_status)) return false
    if (onlyMapped.value && !(record.provenance?.mapping_field_count > 0)) return false

    if (!term) return true

    const haystack = [
      record.record_title,
      String(record.local_record_id || ''),
      String(record.zenodo_record_id || ''),
      String(record.zenodo_doi || ''),
      String(record.concept_rec_id || ''),
    ]
      .join(' ')
      .toLowerCase()

    return haystack.includes(term)
  })

  list = [...list]
  if (sortBy.value === 'title_asc') {
    list.sort((a, b) => String(a.record_title || '').localeCompare(String(b.record_title || '')))
  } else if (sortBy.value === 'title_desc') {
    list.sort((a, b) => String(b.record_title || '').localeCompare(String(a.record_title || '')))
  } else if (sortBy.value === 'updated_asc') {
    list.sort((a, b) => new Date(a.updated_at || 0) - new Date(b.updated_at || 0))
  } else {
    list.sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))
  }

  return list
})

const downloadJson = () => {
  if (!payload.value) return
  const jsonString = JSON.stringify(payload.value, null, 2)
  const blob = new Blob([jsonString], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `session_${route.params.sessionId}_zenodo_records.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const handleDownloadHdpc = async () => {
  if (!payload.value?.session?.id) return
  downloadingHdpc.value = 'raw'
  try {
    const blob = await fileService.downloadHdpc(payload.value.session.id)
    downloadBlob(blob, `session_${payload.value.session.id}.hdpc`)
    toast.success('Downloaded .hdpc file')
  } catch (err) {
    console.error('Failed to download .hdpc:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to download .hdpc file')
  } finally {
    downloadingHdpc.value = ''
  }
}

const handleDownloadSharedHdpc = async () => {
  if (!payload.value?.session?.id) return
  downloadingHdpc.value = 'shared'
  try {
    const blob = await fileService.downloadSharedHdpc(payload.value.session.id)
    downloadBlob(blob, `session_${payload.value.session.id}_shared.hdpc`)
    toast.success('Downloaded shared .hdpc export')
  } catch (err) {
    console.error('Failed to download shared .hdpc export:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to download shared export')
  } finally {
    downloadingHdpc.value = ''
  }
}

const copyZenodoIds = async () => {
  const ids = records.value
    .map((record) => record.zenodo_record_id)
    .filter(Boolean)
    .map((value) => String(value))

  if (!ids.length) {
    toast.error('No Zenodo record IDs available to copy')
    return
  }

  try {
    await navigator.clipboard.writeText(ids.join('\n'))
    toast.success('Zenodo IDs copied to clipboard')
  } catch {
    toast.error('Could not copy IDs to clipboard')
  }
}

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push('/submissions')
}

const clearBatchPolling = () => {
  if (batchPollTimer) {
    window.clearTimeout(batchPollTimer)
    batchPollTimer = null
  }
  batchPolling.value = false
}

const scheduleBatchPoll = (taskId) => {
  clearBatchPolling()
  if (!taskId) return
  batchPolling.value = true
  batchPollTimer = window.setTimeout(async () => {
    try {
      const response = await submissionService.getSessionBatchOperation(Number(route.params.sessionId), taskId)
      batchTaskStatus.value = response.data
      const state = String(response.data?.state || '').toUpperCase()
      if (!['SUCCESS', 'FAILURE'].includes(state)) {
        scheduleBatchPoll(taskId)
        return
      }
      await Promise.all([loadRecords(), refreshMergedData()])
      if (state === 'SUCCESS') {
        toast.success('Session batch operation completed')
      } else {
        toast.error(response.data?.error || 'Session batch operation failed')
      }
      activeBatchTaskId.value = ''
      clearBatchPolling()
    } catch (err) {
      clearBatchPolling()
      toast.error(err.error?.message || err.error || err.message || 'Failed to refresh batch operation status')
    }
  }, 2000)
}

const loadRecords = async () => {
  try {
    const sessionId = Number(route.params.sessionId)
    const response = await submissionService.getSessionRecords(sessionId)
    payload.value = response.data
  } catch (err) {
    console.error('Failed to load session records:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load session records.'
  }
}

const refreshMergedData = async () => {
  const sessionId = Number(route.params.sessionId)
  const [workspaceResponse, tasksResponse] = await Promise.all([
    submissionService.getSessionWorkspaceSummary(sessionId),
    submissionService.listSessionBatchOperations(sessionId, { limit: 10 }),
  ])
  workspaceSummary.value = workspaceResponse.data
  batchTasks.value = tasksResponse.data?.tasks || []
  if (!activeBatchTaskId.value && batchTasks.value.length > 0) {
    const latestTaskId = batchTasks.value[0]?.task_id
    if (latestTaskId) {
      activeBatchTaskId.value = latestTaskId
      const latestTask = await submissionService.getSessionBatchOperation(sessionId, latestTaskId)
      batchTaskStatus.value = latestTask.data
      const state = String(latestTask.data?.state || '').toUpperCase()
      if (!['SUCCESS', 'FAILURE'].includes(state)) {
        scheduleBatchPoll(latestTaskId)
      }
    }
  }
}

const launchBatchOperation = async (operationType) => {
  if (sessionIsExplorerOnly.value) {
    toast.error('Explorer-only sessions do not allow workflow or publishing operations')
    return
  }
  const sessionId = Number(route.params.sessionId)
  batchLaunching.value = operationType
  try {
    const response = await submissionService.launchSessionBatchOperation(sessionId, {
      operation_type: operationType,
    })
    const taskId = response.data?.task_id
    activeBatchTaskId.value = taskId || ''
    if (taskId) {
      toast.success('Session batch operation queued')
      scheduleBatchPoll(taskId)
    }
    await refreshMergedData()
  } catch (err) {
    console.error('Failed to launch session batch operation:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to queue session batch operation')
  } finally {
    batchLaunching.value = ''
  }
}

const createVersion = async (record) => {
  if (sessionIsExplorerOnly.value) {
    toast.error('Explorer-only sessions do not allow version creation')
    return
  }
  const sessionId = Number(route.params.sessionId)
  if (!record?.local_record_id) return
  if (!window.confirm(`Create a new Zenodo version draft for "${record.record_title || record.source_file_name}" using the complete local file set?`)) {
    return
  }

  versioningRecordId.value = record.local_record_id
  try {
    const response = await submissionService.createSessionRecordVersion(sessionId, record.local_record_id, { publish: false })
    const newLocalRecordId = response.data?.new_version?.new_local_record_id
    toast.success(newLocalRecordId ? `New version draft created as local record #${newLocalRecordId}` : 'New version draft created')
    await loadRecords()
  } catch (err) {
    console.error('Failed to create new version:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to create new Zenodo version')
  } finally {
    versioningRecordId.value = null
  }
}

const handleGovernanceUpdated = async (updatedSession) => {
  governanceOpen.value = false
  if (payload.value && updatedSession) {
    payload.value = {
      ...payload.value,
      session: updatedSession,
    }
  }
  try {
    await Promise.all([loadRecords(), refreshMergedData()])
  } catch (err) {
    console.error('Failed to refresh session after governance update:', err)
    toast.error(err.error?.message || err.error || err.message || 'Session updated, but the record view did not refresh cleanly')
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadRecords(), refreshMergedData()])
  } catch (err) {
    console.error('Failed to load session intelligence:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load session intelligence.'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  clearBatchPolling()
})
</script>
