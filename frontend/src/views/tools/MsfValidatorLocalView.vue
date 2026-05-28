<template>
  <div class="space-y-6">
    <div class="bg-white rounded-lg shadow p-6">
      <div class="flex items-start justify-between">
        <div>
          <h2 class="text-xl font-semibold text-gray-900">MSF Validator (Local)</h2>
          <p class="mt-1 text-sm text-gray-600">
            Analyze, repair, and export MSF files against attached workstation or server/HPC input directories.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="inline-flex h-7 w-7 items-center justify-center rounded-full border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900"
            title="Open MSF Validator help"
            @click="showInfoModal = true"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span class="sr-only">MSF Validator help</span>
          </button>
          <span
            class="px-3 py-1 text-xs font-semibold rounded-full"
            :class="isFeatureEnabled ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'"
          >
            {{ isFeatureEnabled ? 'Enabled' : 'Disabled' }}
          </span>
        </div>
      </div>

      <div v-if="!isFeatureEnabled" class="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <p class="font-medium">This tool is available only for Admin users in attached filesystem mode.</p>
        <ul class="mt-2 list-disc pl-5 space-y-1 text-xs">
          <li v-for="reason in disabledReasons" :key="reason">{{ reason }}</li>
        </ul>
      </div>

      <div class="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Select MSF from Local Input
          </label>
          <select
            v-model="selectedMsfPath"
            :disabled="!isFeatureEnabled || loadingContext"
            class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100"
          >
            <option value="" disabled>-- Select an MSF file --</option>
            <option v-for="file in context.msf_files || []" :key="file.full_path" :value="file.full_path">
              {{ file.path }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Subdirectory (optional)
          </label>
          <div class="mt-1 flex rounded-md shadow-sm">
            <span class="inline-flex items-center px-3 rounded-l-md border border-r-0 border-gray-300 bg-gray-50 text-gray-500 text-xs">
              {{ context.input_root || '/data/local_input' }}/
            </span>
            <input
              v-model="directoryPath"
              :disabled="!isFeatureEnabled"
              type="text"
              placeholder="rcin"
              class="flex-1 min-w-0 block w-full px-3 py-2 rounded-none rounded-r-md border-gray-300 focus:ring-indigo-500 focus:border-indigo-500 text-sm disabled:bg-gray-100"
            />
          </div>
        </div>
      </div>

      <div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="includeReferenceCheck" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Check referenced files in directory</span>
        </label>
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="recursiveScan" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Recursive scan</span>
        </label>
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="trimWhitespaceEnabled" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Trim whitespace in all columns</span>
        </label>
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="normalizeFilenameEnabled" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Normalize filename values</span>
        </label>
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="removeEmptyRowsEnabled" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Remove fully empty rows</span>
        </label>
      </div>

      <div v-if="isCsvSelected" class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="useFirstRowAsHeader" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Use first row as header</span>
        </label>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            CSV Delimiter (optional)
          </label>
          <input
            v-model="csvDelimiter"
            :disabled="!isFeatureEnabled"
            type="text"
            placeholder=", or ;"
            class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
          />
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg shadow p-6 space-y-6">
      <h3 class="text-lg font-semibold text-gray-900">Duplicate Scan & Resolve</h3>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">
          Columns to scan for duplicates
        </label>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
          <label
            v-for="column in knownColumns"
            :key="`scan-${column}`"
            class="inline-flex items-center space-x-2 text-xs text-gray-700"
          >
            <input
              v-model="duplicateScanColumns"
              :disabled="!isFeatureEnabled"
              type="checkbox"
              :value="column"
              class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span>{{ column }}</span>
          </label>
        </div>
        <p class="mt-2 text-xs text-gray-500">
          Run once to load columns if this list is empty.
        </p>
      </div>

      <div class="border rounded-md p-4 space-y-3 bg-gray-50">
        <label class="flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="duplicateResolveEnabled" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Apply duplicate resolution</span>
        </label>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Resolution Strategy</label>
            <select
              v-model="duplicateResolveStrategy"
              :disabled="!isFeatureEnabled || !duplicateResolveEnabled"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            >
              <option value="keep_first">Keep first</option>
              <option value="keep_last">Keep last</option>
              <option value="merge_non_empty">Merge non-empty</option>
              <option value="suffix_with_filename">Suffix with filename</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Columns for duplicate key</label>
            <select
              v-model="duplicateResolveColumns"
              multiple
              :disabled="!isFeatureEnabled || !duplicateResolveEnabled"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100 min-h-[90px]"
            >
              <option v-for="column in knownColumns" :key="`resolve-${column}`" :value="column">
                {{ column }}
              </option>
            </select>
          </div>
        </div>

        <div v-if="duplicateResolveStrategy === 'suffix_with_filename'" class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Target column</label>
            <select
              v-model="duplicateSuffixTargetColumn"
              :disabled="!isFeatureEnabled || !duplicateResolveEnabled"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            >
              <option value="" disabled>-- Select --</option>
              <option v-for="column in knownColumns" :key="`target-${column}`" :value="column">
                {{ column }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Filename column</label>
            <select
              v-model="duplicateSuffixFilenameColumn"
              :disabled="!isFeatureEnabled || !duplicateResolveEnabled"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            >
              <option value="">Auto-detect</option>
              <option v-for="column in knownColumns" :key="`filename-${column}`" :value="column">
                {{ column }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Delimiter</label>
            <input
              v-model="duplicateSuffixDelimiter"
              :disabled="!isFeatureEnabled || !duplicateResolveEnabled"
              type="text"
              placeholder="—"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            />
            <label class="mt-2 inline-flex items-center space-x-2 text-xs text-gray-700">
              <input v-model="duplicateSuffixAutoSpace" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              <span>Auto spacing around delimiter</span>
            </label>
          </div>
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg shadow p-6 space-y-6">
      <h3 class="text-lg font-semibold text-gray-900">Column Merge</h3>
      <label class="flex items-center space-x-2 text-sm text-gray-700">
        <input v-model="mergeColumnsEnabled" :disabled="!isFeatureEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
        <span>Merge values from source columns into one target column</span>
      </label>
      <p class="text-xs text-gray-500">
        Choose source columns in order, then write into an existing column or a new column.
      </p>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-medium text-gray-700 mb-1">Source columns</label>
          <select
            v-model="mergeSourceColumns"
            multiple
            :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
            class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100 min-h-[90px]"
          >
            <option v-for="column in knownColumns" :key="`merge-source-${column}`" :value="column">
              {{ column }}
            </option>
          </select>
        </div>
        <div class="space-y-2">
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Target mode</label>
            <div class="grid grid-cols-2 gap-2">
              <label class="inline-flex items-center gap-2 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700">
                <input
                  v-model="mergeTargetMode"
                  :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
                  type="radio"
                  value="existing"
                  class="border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span>Existing column</span>
              </label>
              <label class="inline-flex items-center gap-2 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700">
                <input
                  v-model="mergeTargetMode"
                  :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
                  type="radio"
                  value="new"
                  class="border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span>New column</span>
              </label>
            </div>
          </div>
          <div v-if="mergeTargetMode === 'existing'">
            <label class="block text-xs font-medium text-gray-700 mb-1">Target existing column</label>
            <select
              v-model="mergeExistingTargetColumn"
              :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            >
              <option value="" disabled>-- Select column --</option>
              <option v-for="column in knownColumns" :key="`merge-existing-${column}`" :value="column">
                {{ column }}
              </option>
            </select>
          </div>
          <div v-else>
            <label class="block text-xs font-medium text-gray-700 mb-1">Target new column name</label>
            <input
              v-model="mergeNewTargetColumn"
              :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
              type="text"
              placeholder="merged_title_filename"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-700 mb-1">Delimiter</label>
            <input
              v-model="mergeDelimiter"
              :disabled="!isFeatureEnabled || !mergeColumnsEnabled"
              type="text"
              placeholder="—"
              class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm disabled:bg-gray-100"
            />
          </div>
          <div class="flex items-center space-x-4">
            <label class="inline-flex items-center space-x-2 text-xs text-gray-700">
              <input v-model="mergeAutoSpace" :disabled="!isFeatureEnabled || !mergeColumnsEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              <span>Auto spacing</span>
            </label>
            <label class="inline-flex items-center space-x-2 text-xs text-gray-700">
              <input v-model="mergeSkipEmpty" :disabled="!isFeatureEnabled || !mergeColumnsEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              <span>Skip empty source values</span>
            </label>
            <label class="inline-flex items-center space-x-2 text-xs text-gray-700">
              <input v-model="mergeOverwrite" :disabled="!isFeatureEnabled || !mergeColumnsEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
              <span>Overwrite existing values</span>
            </label>
          </div>
        </div>
      </div>

      <div class="flex justify-end">
        <button
          @click="runValidator"
          :disabled="!canRun || running"
          class="px-5 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ running ? 'Running…' : 'Run Checks & Operations' }}
        </button>
      </div>
    </div>

    <div v-if="result" class="bg-white rounded-lg shadow p-6 space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-gray-900">Result</h3>
        <div class="flex space-x-2">
          <button
            @click="downloadExport('csv')"
            :disabled="downloading"
            class="px-3 py-1.5 text-sm bg-gray-100 text-gray-800 rounded hover:bg-gray-200 disabled:opacity-50"
          >
            Download CSV
          </button>
          <button
            @click="downloadExport('xlsx')"
            :disabled="downloading"
            class="px-3 py-1.5 text-sm bg-gray-100 text-gray-800 rounded hover:bg-gray-200 disabled:opacity-50"
          >
            Download XLSX
          </button>
        </div>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Rows (original)</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_original ?? 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Rows (after)</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_after_operations ?? 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Operations applied</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.operations_applied ?? 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Filename column</p>
          <p class="text-sm font-semibold text-gray-900 truncate">{{ result.filename_column || 'n/a' }}</p>
        </div>
      </div>

      <div v-if="(result.blockers || []).length > 0" class="rounded-md border border-red-200 bg-red-50 p-4">
        <p class="text-sm font-semibold text-red-700">Blockers</p>
        <ul class="mt-2 list-disc pl-5 text-xs text-red-700 space-y-1">
          <li v-for="msg in result.blockers" :key="`blocker-${msg}`">{{ msg }}</li>
        </ul>
      </div>

      <div v-if="(result.warnings || []).length > 0" class="rounded-md border border-amber-200 bg-amber-50 p-4">
        <p class="text-sm font-semibold text-amber-800">Warnings</p>
        <ul class="mt-2 list-disc pl-5 text-xs text-amber-800 space-y-1">
          <li v-for="msg in result.warnings" :key="`warning-${msg}`">{{ msg }}</li>
        </ul>
      </div>

      <div v-if="result.checks?.reference_availability" class="rounded border p-4">
        <h4 class="text-sm font-semibold text-gray-900">Referenced File Availability</h4>
        <div class="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <div>Matched: <span class="font-semibold">{{ result.checks.reference_availability.matched_count }}</span></div>
          <div>Missing: <span class="font-semibold">{{ result.checks.reference_availability.missing_count }}</span></div>
          <div>Unmapped: <span class="font-semibold">{{ result.checks.reference_availability.unmapped_count }}</span></div>
          <div>Implicit: <span class="font-semibold">{{ result.checks.reference_availability.implicitly_included_count }}</span></div>
        </div>
      </div>

      <div v-if="duplicateSummaryRows.length > 0" class="rounded border p-4">
        <h4 class="text-sm font-semibold text-gray-900">Duplicate Scan</h4>
        <div class="mt-2 space-y-2 text-xs">
          <div
            v-for="row in duplicateSummaryRows"
            :key="`dup-${row.column}`"
            class="rounded border border-gray-200 p-2"
          >
            <p class="font-medium text-gray-900">
              {{ row.column }}: {{ row.beforeGroups }} groups before / {{ row.afterGroups }} groups after
            </p>
            <p class="text-gray-600">
              Rows involved: {{ row.beforeRows }} before / {{ row.afterRows }} after
            </p>
          </div>
        </div>
      </div>

      <div v-if="duplicateResolutionReports.length > 0" class="rounded border p-4">
        <h4 class="text-sm font-semibold text-gray-900">Duplicate Resolution Details</h4>
        <div class="mt-2 space-y-2 text-xs">
          <div
            v-for="(row, idx) in duplicateResolutionReports"
            :key="`dup-solved-${idx}`"
            class="rounded border border-gray-200 p-2"
          >
            <p class="font-medium text-gray-900">
              Strategy: {{ formatDuplicateStrategy(row.strategy) }}
            </p>
            <p class="text-gray-700">
              Groups detected: {{ row.groups_detected || 0 }},
              rows removed: {{ row.rows_removed || 0 }},
              rows merged: {{ row.rows_merged || 0 }},
              cell updates: {{ row.rows_affected || 0 }}
            </p>
          </div>
        </div>
      </div>

      <div v-if="(result.actions || []).length > 0" class="rounded border p-4">
        <h4 class="text-sm font-semibold text-gray-900">Applied Actions</h4>
        <ul class="mt-2 list-disc pl-5 text-xs text-gray-700 space-y-1">
          <li v-for="(item, idx) in result.actions" :key="`action-${idx}`">{{ item }}</li>
        </ul>
      </div>

      <div class="rounded border p-4 overflow-x-auto">
        <h4 class="text-sm font-semibold text-gray-900 mb-2">Preview</h4>
        <table class="min-w-full text-xs text-left border-collapse">
          <thead>
            <tr>
              <th
                v-for="column in result.preview?.columns || []"
                :key="`preview-head-${column}`"
                class="px-2 py-1 border-b bg-gray-50 text-gray-700"
              >
                {{ column }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, idx) in result.preview?.preview_rows || []"
              :key="`preview-row-${idx}`"
              class="odd:bg-white even:bg-gray-50"
            >
              <td
                v-for="column in result.preview?.columns || []"
                :key="`preview-cell-${idx}-${column}`"
                class="px-2 py-1 border-b text-gray-700 whitespace-nowrap"
              >
                {{ row[column] || '' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div
      v-if="showInfoModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/60 p-4"
      @click.self="showInfoModal = false"
    >
      <div class="w-full max-w-3xl rounded-lg bg-white shadow-xl">
        <div class="flex items-start justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h3 class="text-lg font-semibold text-gray-900">How To Use MSF Validator (Local)</h3>
            <p class="mt-1 text-xs text-gray-600">
              Practical guidance with examples for duplicate handling, column merge, and export.
            </p>
          </div>
          <button
            type="button"
            class="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
            @click="showInfoModal = false"
          >
            Close
          </button>
        </div>

        <div class="max-h-[70vh] overflow-y-auto px-5 py-4 space-y-5 text-sm text-gray-700">
          <section class="space-y-2">
            <h4 class="font-semibold text-gray-900">1. Basic flow</h4>
            <ol class="list-decimal pl-5 text-xs space-y-1">
              <li>Select an MSF file and optional subdirectory.</li>
              <li>Enable checks and operations you want to apply.</li>
              <li>Run checks, review blockers/warnings, then export CSV/XLSX.</li>
            </ol>
          </section>

          <section class="space-y-2">
            <h4 class="font-semibold text-gray-900">2. Duplicate strategy choices</h4>
            <ul class="list-disc pl-5 text-xs space-y-1">
              <li><span class="font-medium">Keep first</span>: retains the first row in each duplicate group.</li>
              <li><span class="font-medium">Keep last</span>: retains the last row in each duplicate group.</li>
              <li><span class="font-medium">Merge non-empty</span>: fills empty cells from later duplicates before dropping them.</li>
              <li><span class="font-medium">Suffix with filename</span>: appends the filename to a target field to make duplicate labels unique.</li>
            </ul>
          </section>

          <section class="space-y-2">
            <h4 class="font-semibold text-gray-900">3. Column Merge examples</h4>
            <div class="rounded border border-gray-200 bg-gray-50 p-3 text-xs space-y-1">
              <p class="font-medium text-gray-900">Example A: merge into existing column</p>
              <p>Source columns: <span class="font-mono">title, filename</span></p>
              <p>Target mode: <span class="font-mono">Existing column</span> and target <span class="font-mono">title</span></p>
              <p>Delimiter: <span class="font-mono">—</span>, overwrite: <span class="font-mono">true</span></p>
              <p>Result: <span class="font-mono">Document A — document_3345.pdf</span></p>
            </div>
            <div class="rounded border border-gray-200 bg-gray-50 p-3 text-xs space-y-1">
              <p class="font-medium text-gray-900">Example B: merge into new column</p>
              <p>Source columns: <span class="font-mono">title, filename</span></p>
              <p>Target mode: <span class="font-mono">New column</span> and name <span class="font-mono">title_with_file</span></p>
              <p>Original fields stay unchanged; merged text is written into the new field.</p>
            </div>
          </section>

          <section class="space-y-2">
            <h4 class="font-semibold text-gray-900">4. Understanding results</h4>
            <ul class="list-disc pl-5 text-xs space-y-1">
              <li><span class="font-medium">Duplicate Scan</span> compares before/after duplicate counts.</li>
              <li><span class="font-medium">Duplicate Resolution Details</span> reports strategy and rows removed/merged.</li>
              <li><span class="font-medium">Applied Actions</span> lists each successful operation in execution order.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import msfService from '@/services/msf.service'
import { useToast } from '@/composables/useToast'

const { success, error: showError } = useToast()

const loadingContext = ref(false)
const running = ref(false)
const downloading = ref(false)
const showInfoModal = ref(false)

const context = ref({
  enabled: false,
  is_admin: false,
  storage_mode: null,
  input_root: '',
  reasons: [],
  msf_files: []
})

const selectedMsfPath = ref('')
const directoryPath = ref('')
const includeReferenceCheck = ref(true)
const recursiveScan = ref(true)
const trimWhitespaceEnabled = ref(false)
const normalizeFilenameEnabled = ref(false)
const removeEmptyRowsEnabled = ref(false)

const useFirstRowAsHeader = ref(true)
const csvDelimiter = ref('')

const knownColumns = ref([])
const duplicateScanColumns = ref([])

const duplicateResolveEnabled = ref(false)
const duplicateResolveColumns = ref([])
const duplicateResolveStrategy = ref('merge_non_empty')
const duplicateSuffixTargetColumn = ref('')
const duplicateSuffixFilenameColumn = ref('')
const duplicateSuffixDelimiter = ref('—')
const duplicateSuffixAutoSpace = ref(true)

const mergeColumnsEnabled = ref(false)
const mergeSourceColumns = ref([])
const mergeTargetMode = ref('existing')
const mergeExistingTargetColumn = ref('title')
const mergeNewTargetColumn = ref('merged_column')
const mergeDelimiter = ref('—')
const mergeAutoSpace = ref(true)
const mergeSkipEmpty = ref(true)
const mergeOverwrite = ref(true)

const result = ref(null)

const isFeatureEnabled = computed(() => !!context.value.enabled)
const disabledReasons = computed(() => context.value.reasons || [])
const isCsvSelected = computed(() => selectedMsfPath.value.toLowerCase().endsWith('.csv'))
const canRun = computed(() => isFeatureEnabled.value && !!selectedMsfPath.value && !running.value)

const duplicateSummaryRows = computed(() => {
  if (!result.value?.checks) return []
  const before = result.value.checks.duplicates_before_operations?.by_column || {}
  const after = result.value.checks.duplicates_after_operations?.by_column || {}
  return Object.keys(before).map((column) => ({
    column,
    beforeGroups: before[column]?.duplicate_group_count || 0,
    beforeRows: before[column]?.duplicate_row_count || 0,
    afterGroups: after[column]?.duplicate_group_count || 0,
    afterRows: after[column]?.duplicate_row_count || 0
  }))
})

const duplicateResolutionReports = computed(() => {
  const operations = result.value?.operations || []
  return operations.filter((item) => item?.type === 'resolve_duplicates' && item?.status === 'ok')
})

const mergeTargetColumnValue = computed(() => {
  if (mergeTargetMode.value === 'new') {
    return mergeNewTargetColumn.value.trim()
  }
  return mergeExistingTargetColumn.value.trim()
})

watch(selectedMsfPath, () => {
  result.value = null
})

watch(knownColumns, (columns) => {
  if (!Array.isArray(columns) || columns.length === 0) return
  if (duplicateScanColumns.value.length === 0) {
    const defaults = ['filename', 'title']
      .filter((name) => columns.includes(name))
    duplicateScanColumns.value = defaults.length > 0 ? defaults : [columns[0]]
  }
  if (duplicateResolveColumns.value.length === 0 && duplicateScanColumns.value.length > 0) {
    duplicateResolveColumns.value = [...duplicateScanColumns.value]
  }
  if (!duplicateSuffixTargetColumn.value && columns.includes('title')) {
    duplicateSuffixTargetColumn.value = 'title'
  }
  if (!duplicateSuffixFilenameColumn.value && columns.includes('filename')) {
    duplicateSuffixFilenameColumn.value = 'filename'
  }
  if (!mergeExistingTargetColumn.value && columns.includes('title')) {
    mergeExistingTargetColumn.value = 'title'
  }
  if (!mergeExistingTargetColumn.value) {
    mergeExistingTargetColumn.value = columns[0]
  }
})

const buildPayload = () => {
  const payload = {
    msf_path: selectedMsfPath.value,
    directory_path: directoryPath.value.trim() || '',
    recursive: recursiveScan.value,
    include_reference_check: includeReferenceCheck.value,
    duplicate_scan_columns: duplicateScanColumns.value
  }

  const parseOptions = {}
  if (isCsvSelected.value) {
    parseOptions.use_first_row_as_header = useFirstRowAsHeader.value
    if (csvDelimiter.value.trim()) {
      parseOptions.delimiter = csvDelimiter.value.trim()
    }
  }
  if (Object.keys(parseOptions).length > 0) {
    payload.parse_options = parseOptions
  }

  const operations = []
  if (trimWhitespaceEnabled.value) {
    operations.push({ type: 'trim_whitespace' })
  }
  if (normalizeFilenameEnabled.value) {
    operations.push({ type: 'normalize_filename_column' })
  }
  if (removeEmptyRowsEnabled.value) {
    operations.push({ type: 'remove_empty_rows' })
  }
  if (duplicateResolveEnabled.value) {
    const op = {
      type: 'resolve_duplicates',
      columns:
        duplicateResolveColumns.value.length > 0
          ? duplicateResolveColumns.value
          : duplicateScanColumns.value,
      strategy: duplicateResolveStrategy.value
    }
    if (duplicateResolveStrategy.value === 'suffix_with_filename') {
      op.target_column = duplicateSuffixTargetColumn.value || undefined
      op.filename_column = duplicateSuffixFilenameColumn.value || undefined
      op.delimiter = duplicateSuffixDelimiter.value
      op.auto_space = duplicateSuffixAutoSpace.value
    }
    operations.push(op)
  }
  if (mergeColumnsEnabled.value) {
    operations.push({
      type: 'merge_columns',
      source_columns: mergeSourceColumns.value,
      target_column: mergeTargetColumnValue.value,
      delimiter: mergeDelimiter.value,
      auto_space: mergeAutoSpace.value,
      skip_empty: mergeSkipEmpty.value,
      overwrite: mergeOverwrite.value
    })
  }

  payload.operations = operations
  return payload
}

const formatDuplicateStrategy = (strategy) => {
  const map = {
    keep_first: 'Keep first',
    keep_last: 'Keep last',
    merge_non_empty: 'Merge non-empty',
    suffix_with_filename: 'Suffix with filename'
  }
  return map[strategy] || strategy || 'Unknown'
}

const runValidator = async () => {
  if (!canRun.value) return
  running.value = true
  try {
    const response = await msfService.validateLocalMsf(buildPayload())
    result.value = response.data || null
    knownColumns.value = result.value?.preview?.columns || knownColumns.value
    success('MSF validator run completed.')
  } catch (e) {
    showError(e?.message || 'Failed to run local MSF validator.')
  } finally {
    running.value = false
  }
}

const downloadExport = async (format) => {
  if (!isFeatureEnabled.value || !selectedMsfPath.value) return
  downloading.value = true
  try {
    const payload = {
      ...buildPayload(),
      format,
      allow_export_with_blockers: true
    }
    const { blob, filename } = await msfService.exportLocalMsf(payload)
    const link = document.createElement('a')
    const objectUrl = URL.createObjectURL(blob)
    link.href = objectUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(objectUrl)
    success(`Downloaded ${filename}`)
  } catch (e) {
    showError(e?.message || 'Failed to export MSF.')
  } finally {
    downloading.value = false
  }
}

const loadContext = async () => {
  loadingContext.value = true
  try {
    const response = await msfService.getLocalValidatorContext()
    context.value = response.data || context.value
  } catch (e) {
    context.value = {
      enabled: false,
      is_admin: false,
      storage_mode: null,
      input_root: '',
      reasons: ['Failed to load validator context'],
      msf_files: []
    }
  } finally {
    loadingContext.value = false
  }
}

onMounted(loadContext)
</script>
