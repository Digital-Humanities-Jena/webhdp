<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-5xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Upload Files</h1>
        <p class="mt-2 max-w-3xl text-gray-600">
          Upload one self-contained file, or use a batch for datasets and models with separate textures.
        </p>
      </div>

      <StepIndicator
        :current-step="1"
        :batch-mode="uploadMode === 'directory'"
        current-label="Choose your files"
        :current-hint="uploadStepHint"
      />

      <div class="bg-white shadow rounded-lg p-4 sm:p-6 mb-6">
        <fieldset :disabled="uploading || validatingMsf" class="min-w-0">
          <legend class="sr-only">Upload source and workspace</legend>
        <div class="mb-6">
          <h2 class="text-lg font-semibold text-gray-900">Choose workflow path</h2>
          <p class="mt-1 text-sm text-gray-600">
            Pick the path that matches your source material. The application will guide the rest of the workflow accordingly.
          </p>
        </div>

        <div class="grid gap-4 md:grid-cols-2 mb-6">
          <button
            @click="selectUploadPath('file')"
            data-testid="upload-path-manual"
            :aria-pressed="uploadMode === 'file'"
            :class="[
              'rounded-2xl border px-5 py-5 text-left transition-all',
              uploadMode === 'file'
                ? 'border-indigo-500 bg-indigo-50 shadow-sm ring-2 ring-indigo-100'
                : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
            ]"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-base font-semibold" :class="uploadMode === 'file' ? 'text-indigo-950' : 'text-gray-900'">
                  Direct file upload
                </p>
                <p class="mt-1 text-sm" :class="uploadMode === 'file' ? 'text-indigo-900' : 'text-gray-600'">
                  One self-contained model or image, such as a GLB or JPG. Add its description in the next steps.
                </p>
                <p class="mt-3 text-xs uppercase tracking-wide" :class="uploadMode === 'file' ? 'text-indigo-700' : 'text-gray-500'">
                  Input: one file
                </p>
              </div>
              <span class="rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="uploadMode === 'file' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700'">
                Single file
              </span>
            </div>
          </button>
          <button
            @click="selectUploadPath('directory')"
            data-testid="upload-path-batch"
            :aria-pressed="uploadMode === 'directory'"
            :class="[
              'rounded-2xl border px-5 py-5 text-left transition-all',
              uploadMode === 'directory'
                ? 'border-indigo-500 bg-indigo-50 shadow-sm ring-2 ring-indigo-100'
                : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
            ]"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-base font-semibold" :class="uploadMode === 'directory' ? 'text-indigo-950' : 'text-gray-900'">
                  Batch upload with spreadsheet
                </p>
                <p class="mt-1 text-sm" :class="uploadMode === 'directory' ? 'text-indigo-900' : 'text-gray-600'">
                  Multiple models or files with textures. Include a metadata spreadsheet (MSF) to describe each model.
                </p>
                <p class="mt-3 text-xs uppercase tracking-wide" :class="uploadMode === 'directory' ? 'text-indigo-700' : 'text-gray-500'">
                  Input: ZIP + MSF or mounted folder + MSF
                </p>
              </div>
              <span class="rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="uploadMode === 'directory' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700'">
                Batch
              </span>
            </div>
          </button>
        </div>

        <div v-if="uploadMode === 'directory'" class="mb-6 rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
          <div class="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p class="text-sm font-semibold text-gray-900">{{ uploadPathSummary.title }}</p>
              <p class="mt-1 text-sm text-gray-600">{{ uploadPathSummary.description }}</p>
            </div>
            <span
              v-if="uploadMode === 'directory' && storageStatus?.mode"
              class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium"
              :class="{
                'bg-green-100 text-green-800': storageStatus.mode === 'pure_cloud',
                'bg-blue-100 text-blue-800': storageStatus.mode === 'cloud_backup',
                'bg-gray-100 text-gray-800': storageStatus.mode === 'server_only',
                'bg-indigo-100 text-indigo-800': storageStatus.mode === 'local'
              }"
            >
              {{ formatStorageMode(storageStatus.mode) }}
            </span>
          </div>
        </div>

        <details v-if="uploadMode === 'directory'" class="mb-6 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
          <summary class="cursor-pointer text-sm font-semibold text-indigo-900">How to prepare a batch</summary>
          <div class="mt-3 space-y-3 text-sm text-gray-700">
            <p>Keep each model with its materials and textures. Use unique model filenames so spreadsheet rows match unambiguously.</p>
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <p class="font-semibold">Example ZIP contents</p>
                <pre class="mt-2 overflow-x-auto rounded bg-white p-3 text-xs">model.obj
model.mtl
textures/albedo.jpg</pre>
              </div>
              <div>
                <p class="font-semibold">Example spreadsheet row</p>
                <p class="mt-2"><code>filename</code>: <code>model.obj</code><br /><code>title</code>: Example model</p>
                <p class="mt-2">Add one row per main model. Textures and materials do not need their own records.</p>
              </div>
            </div>
            <a href="/examples/batch-metadata.csv" download="batch-metadata.csv" class="inline-block font-medium text-indigo-700 underline">Download example CSV</a>
            <p>Replace the example filename and descriptions with your own. This is a starting layout; the next steps check required metadata and let you repair missing values.</p>
          </div>
        </details>

      <details v-if="showHpcResourcePanel" :open="Boolean(hpcAllocation || hpcAllocationError)" class="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <summary class="cursor-pointer text-sm font-semibold text-slate-900">Rendering resources (HPC) · {{ hpcAllocation ? hpcAllocation.status : 'Prepare when needed' }}</summary>
        <div class="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p class="mt-1 text-sm text-slate-600">
              {{ hpcStatusMessage }}
            </p>
            <p class="mt-2 text-sm text-slate-600">You can upload and review files before requesting resources. Rendering needs a ready compute allocation; a queued request is still waiting for a machine.</p>
            <router-link v-if="hpcStatus && !hpcStatus.can_allocate" to="/hpc-resources" class="mt-2 inline-block text-sm font-medium text-indigo-700 underline">Check or request HPC access</router-link>
            <p v-if="hpcAllocation" class="mt-2 text-xs text-slate-500">
              Allocation {{ hpcAllocation.allocation_id }} · {{ hpcAllocation.status }}
              <span v-if="hpcAllocation.node_name"> · {{ hpcAllocation.node_name }}</span>
            </p>
            <p v-if="hpcAllocationError" class="mt-2 text-sm text-rose-700">
              {{ hpcAllocationError }}
            </p>
          </div>
          <button
            type="button"
            class="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="hpcAllocationLoading || !hpcStatus?.available || !hpcStatus?.can_allocate"
            @click="requestHpcResources"
          >
            {{ hpcAllocationButtonLabel }}
          </button>
        </div>
      </details>

        <details class="mb-6 rounded-xl border border-gray-200 bg-white p-4">
          <summary class="cursor-pointer text-sm font-semibold text-gray-900">
            Workspace and destination · {{ workspaceType === 'institution' ? 'Institution' : 'Personal' }} · {{ defaultZenodoEnvironment === 'production' ? 'Production' : 'Sandbox' }}
          </summary>
          <div class="mt-4">
          <div class="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-base font-semibold text-gray-900">Workspace</h3>
              <p class="mt-1 text-sm text-gray-600">Choose whether this session stays personal or is shared through one of your institution workspaces.</p>
            </div>
            <div class="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                :class="workspaceType === 'personal' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'"
                :aria-pressed="workspaceType === 'personal'"
                @click="workspaceType = 'personal'"
              >
                Personal
              </button>
              <button
                type="button"
                :disabled="!institutionWorkspaceOptions.length"
                class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors disabled:opacity-50"
                :class="workspaceType === 'institution' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'"
                :aria-pressed="workspaceType === 'institution'"
                @click="workspaceType = 'institution'"
              >
                Institution
              </button>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div v-if="workspaceType === 'institution'">
              <label class="block text-sm font-medium text-gray-700 mb-1">Institution workspace</label>
              <select aria-label="Institution workspace" v-model="selectedInstitutionId" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                <option v-for="institution in institutionWorkspaceOptions" :key="institution.id" :value="institution.id">
                  {{ institution.name }} ({{ institution.role }})
                </option>
              </select>
              <p class="mt-2 text-xs text-gray-500">
                {{ selectedWorkspaceInstitution ? `Sessions in ${selectedWorkspaceInstitution.name} can use institution credentials and communities.` : 'No institution workspace selected.' }}
              </p>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Default Zenodo environment</label>
              <select aria-label="Default Zenodo environment" v-model="defaultZenodoEnvironment" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                <option value="sandbox">Sandbox</option>
                <option value="production">Production</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Sharing scope</label>
              <select aria-label="Sharing scope" v-model="sharingScope" :disabled="workspaceType !== 'institution'" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100">
                <option value="private">Private</option>
                <option value="institution">Institution shared</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Publishing credential source</label>
              <select aria-label="Publishing credential source" v-model="credentialPreference" :disabled="workspaceType !== 'institution'" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100">
                <option value="user">Personal credentials</option>
                <option value="institution">Institution credentials</option>
              </select>
            </div>
          </div>

          <label
            v-if="workspaceType === 'institution'"
            class="mt-4 inline-flex items-center gap-2 text-sm text-gray-600"
          >
            <input
              v-model="useInstitutionDefaultCommunities"
              type="checkbox"
              class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            Append the institution's default Zenodo communities to this session by default
          </label>
          </div>
        </details>

        <!-- File Upload Mode -->
        <div v-if="uploadMode === 'file'">
          <div
            data-testid="upload-direct-dropzone"
            @drop.prevent="handleDrop"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            :class="[
              'border-2 border-dashed rounded-lg p-6 sm:p-10 text-center transition-colors focus-within:ring-2 focus-within:ring-indigo-500',
              isDragging ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300'
            ]"
          >
            <div class="space-y-4">
              <svg class="mx-auto h-12 w-12 text-gray-400" stroke="currentColor" fill="none" viewBox="0 0 48 48">
                <path d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>

              <div>
                <label for="file-upload" class="cursor-pointer">
                  <span class="text-indigo-600 hover:text-indigo-500 font-medium">
                    Click to choose a file
                  </span>
                  <span class="text-gray-600"> or drag and drop</span>
                </label>
                <input
                  id="file-upload"
                  type="file"
                  class="sr-only"
                  aria-describedby="direct-file-help"
                  @change="handleFileSelect"
                />
              </div>

              <p id="direct-file-help" class="text-sm text-gray-500">
                Upload a model (GLB, glTF, OBJ, STL, FBX, PLY) or an image. For models with separate materials or textures, use a ZIP batch to keep the files together.
              </p>
            </div>
          </div>

          <!-- Selected Files -->
          <div v-if="selectedFiles.length > 0" class="mt-6">
            <h3 class="text-lg font-medium text-gray-900 mb-4">Selected File</h3>
            <ul class="divide-y divide-gray-200">
              <li v-for="(file, index) in selectedFiles" :key="index" class="py-3 flex justify-between items-center">
                <div class="flex min-w-0 items-center">
                  <svg class="h-5 w-5 shrink-0 text-gray-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M8 4a3 3 0 00-3 3v4a5 5 0 0010 0V7a1 1 0 112 0v4a7 7 0 11-14 0V7a5 5 0 0110 0v4a3 3 0 11-6 0V7a1 1 0 012 0v4a1 1 0 102 0V7a3 3 0 00-3-3z" clip-rule="evenodd" />
                  </svg>
                  <span class="min-w-0 break-all text-sm text-gray-900">{{ file.name }}</span>
                  <span class="ml-2 shrink-0 whitespace-nowrap text-xs text-gray-500">({{ formatFileSize(file.size) }})</span>
                </div>
                <button @click="removeFile(index)" :aria-label="`Remove ${file.name}`" class="shrink-0 p-2 text-red-600 hover:text-red-800">
                  <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                  </svg>
                </button>
              </li>
            </ul>
          </div>
        </div>

        <!-- Directory Mode (ZIP Upload) -->
        <div v-else>
          <div class="space-y-6">
            <!-- Loading Indicator -->
            <div v-if="isConnecting" class="rounded-md bg-blue-50 p-4 mb-4">
              <div class="flex">
                <div class="flex-shrink-0">
                  <svg class="h-5 w-5 text-blue-400 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                </div>
                <div class="ml-3">
                  <h3 class="text-sm font-medium text-blue-800">Connecting to cloud storage services...</h3>
                </div>
              </div>
            </div>

            <!-- Storage Status Indicator -->
            <div v-else-if="storageStatus" class="rounded-md p-4" :class="storageStatus.available ? 'bg-green-50' : 'bg-red-50'">
              <div class="flex items-center justify-between">
                <div class="flex items-center">
                  <svg v-if="storageStatus.available" class="h-5 w-5 text-green-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
                  </svg>
                  <svg v-else class="h-5 w-5 text-red-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                  </svg>
                  <div>
                    <span :class="storageStatus.available ? 'text-green-800' : 'text-red-800'" class="text-sm font-medium">
                      {{ formatStorageType(storageStatus.type) }}
                    </span>
                    <span class="text-sm text-gray-600 ml-2">{{ storageStatus.message }}</span>
                  </div>
                </div>
                  <span v-if="storageStatus.mode" class="px-2 py-1 text-xs font-medium rounded-full"
                    :class="{
                      'bg-green-100 text-green-800': storageStatus.mode === 'pure_cloud',
                      'bg-blue-100 text-blue-800': storageStatus.mode === 'cloud_backup',
                      'bg-gray-100 text-gray-800': storageStatus.mode === 'server_only',
                      'bg-indigo-100 text-indigo-800': storageStatus.mode === 'local'
                    }">
                    {{ formatStorageMode(storageStatus.mode) }}
                  </span>
              </div>
            </div>

            <!-- ZIP File Upload (Hidden in Local Mode) -->
            <div v-if="storageStatus?.mode !== 'local'">
              <label class="block text-sm font-medium text-gray-700 mb-2">
                Model Files (ZIP) <span class="text-red-500">*</span>
              </label>

              <!-- ZIP Upload Zone -->
              <div
                @drop.prevent="handleZipDrop"
                @dragover.prevent="isZipDragging = true"
                @dragleave.prevent="isZipDragging = false"
                :class="[
                  'border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer focus-within:ring-2 focus-within:ring-indigo-500',
                  isZipDragging ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300 hover:border-gray-400'
                ]"
                @click="$refs.zipFileInput.click()"
              >
                <input
                  ref="zipFileInput"
                  data-testid="upload-zip-input"
                  aria-label="Model files ZIP"
                  type="file"
                  class="sr-only"
                  @click.stop
                  accept=".zip"
                  @change="handleZipFileSelect"
                />

                <div v-if="!zipFile" class="space-y-2">
                  <svg class="mx-auto h-10 w-10 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                  </svg>
                  <p class="text-sm text-gray-600">
                    <span class="text-indigo-600 font-medium">Click to select</span> or drag and drop
                  </p>
                  <p class="text-xs text-gray-500">ZIP file containing your 3D model files</p>
                </div>

                <div v-else class="flex items-center justify-center space-x-3">
                  <svg class="h-8 w-8 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                  </svg>
                  <div class="text-left">
                    <p class="text-sm font-medium text-gray-900">{{ zipFile.name }}</p>
                    <p class="text-xs text-gray-500">{{ formatFileSize(zipFile.size) }}</p>
                  </div>
                  <button
                    aria-label="Remove ZIP file"
                    @click.stop="removeZipFile"
                    class="text-red-500 hover:text-red-700"
                    title="Remove file"
                  >
                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <!-- Local Mode MSF Selection -->
            <div v-if="storageStatus?.mode === 'local'" class="space-y-4">
              <!-- Directory Path Selection -->
              <div>
                <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <label class="block text-sm font-medium text-gray-700">
                    Target Directory
                  </label>
                  <span class="text-xs text-gray-500">
                    {{ filteredLocalSubdirectories.length }} of {{ availableLocalSubdirectories.length }} director{{ availableLocalSubdirectories.length === 1 ? 'y' : 'ies' }}
                  </span>
                </div>
                <div class="mt-2 rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <div class="flex flex-col gap-3 lg:flex-row lg:items-center">
                    <input
                      v-model="directorySearchQuery"
                      type="search"
                      :placeholder="directorySearchPlaceholder"
                      class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                    >
                    <button
                      v-if="directorySearchQuery"
                      type="button"
                      class="px-3 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50"
                      @click="directorySearchQuery = ''"
                    >
                      Clear
                    </button>
                  </div>
                  <p class="mt-3 text-xs text-gray-500">
                    Search across nested directories, then choose the narrowest path that uniquely contains the intended model set.
                  </p>
                  <div class="mt-4 max-h-72 space-y-2 overflow-y-auto pr-1">
                    <button
                      type="button"
                      :disabled="loadingLocalMsf"
                      class="w-full rounded-xl border px-4 py-3 text-left transition"
                      :class="!directoryPath ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 bg-white hover:border-gray-300'"
                      @click="selectLocalDirectory('')"
                    >
                      <div class="flex items-center justify-between gap-4">
                        <div>
                          <p class="text-sm font-semibold text-gray-900">Root directory</p>
                          <p class="mt-1 text-xs font-mono text-gray-500 break-all">{{ localInputRoot || '/data/local_input' }}</p>
                        </div>
                        <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">All files</span>
                      </div>
                    </button>

                    <div
                      v-if="!visibleLocalSubdirectories.length"
                      class="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-5 text-sm text-gray-500"
                    >
                      No directories match the current filter.
                    </div>

                    <button
                      v-for="subdir in visibleLocalSubdirectories"
                      :key="`subdir-${subdir.relative_path}`"
                      type="button"
                      :disabled="loadingLocalMsf"
                      class="w-full rounded-xl border px-4 py-3 text-left transition"
                      :class="directoryPath === subdir.relative_path ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 bg-white hover:border-gray-300'"
                      @click="selectLocalDirectory(subdir.relative_path)"
                    >
                      <div class="flex items-start justify-between gap-4">
                        <div class="min-w-0">
                          <p class="text-sm font-semibold text-gray-900 break-all">{{ subdir.relative_path }}</p>
                          <p class="mt-1 text-xs text-gray-500">
                            Depth {{ subdir.depth }} · {{ subdir.file_count }} recursive file{{ subdir.file_count === 1 ? '' : 's' }}
                            <span v-if="subdir.direct_file_count !== subdir.file_count">
                              · {{ subdir.direct_file_count }} directly inside this directory
                            </span>
                          </p>
                        </div>
                        <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                          {{ subdir.file_count }} file{{ subdir.file_count === 1 ? '' : 's' }}
                        </span>
                      </div>
                    </button>
                  </div>
                  <div v-if="filteredLocalSubdirectories.length > 0" class="mt-4 flex flex-col gap-3 border-t border-gray-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <p class="text-xs text-gray-500">
                      Page {{ directoryPage }} of {{ totalDirectoryPages }} · showing {{ visibleLocalSubdirectories.length }} director{{ visibleLocalSubdirectories.length === 1 ? 'y' : 'ies' }} on this page
                    </p>
                    <div class="flex gap-2">
                      <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                        :disabled="directoryPage <= 1"
                        @click="goToPreviousDirectoryPage"
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                        :disabled="directoryPage >= totalDirectoryPages"
                        @click="goToNextDirectoryPage"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                  <p class="mt-3 text-xs text-gray-600">
                    Selected target:
                    <span class="font-medium text-gray-900">
                      {{ selectedLocalDirectory?.relative_path || `Root directory (${localInputRoot || '/data/local_input'})` }}
                    </span>
                  </p>
                </div>
              </div>

              <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">
                  Select metadata source file (MSF) from {{ localScanLabel }} <span class="text-red-500">*</span>
                </label>
                <div v-if="loadingLocalMsf" class="flex items-center space-x-2 text-sm text-gray-500">
                  <svg class="animate-spin h-4 w-4 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>Scanning {{ localScanLabel.toLowerCase() }}...</span>
                </div>
                <div v-else class="rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div class="min-w-0 flex-1">
                      <input
                        v-model="msfSearchQuery"
                        type="search"
                        placeholder="Search MSF files by name or path"
                        class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                      >
                    </div>
                    <span class="text-xs text-gray-500">
                      {{ filteredMsfFiles.length }} of {{ availableMsfFiles.length }} MSF file{{ availableMsfFiles.length === 1 ? '' : 's' }}
                    </span>
                  </div>

                  <div v-if="selectedMsfFileEntry" class="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
                    <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">Selected MSF</p>
                    <p class="mt-1 text-sm font-semibold text-indigo-950">{{ selectedMsfFileEntry.name }}</p>
                    <p class="mt-1 text-xs font-mono text-indigo-900/80 break-all">{{ selectedMsfFileEntry.path }}</p>
                  </div>

                  <div class="mt-4 max-h-72 space-y-2 overflow-y-auto pr-1">
                    <div
                      v-if="!visibleMsfFiles.length"
                      class="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-5 text-sm text-gray-500"
                    >
                      No MSF files match the current filter.
                    </div>
                    <button
                      v-for="file in visibleMsfFiles"
                      :key="file.path"
                      type="button"
                      class="w-full rounded-xl border px-4 py-3 text-left transition"
                      :class="selectedMsfPath === (file.full_path || file.path) ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 bg-white hover:border-gray-300'"
                      @click="selectMsfFile(file)"
                    >
                      <div class="flex items-start justify-between gap-4">
                        <div class="min-w-0">
                          <p class="text-sm font-semibold text-gray-900 break-all">{{ file.name }}</p>
                          <p class="mt-1 text-xs font-mono text-gray-500 break-all">{{ file.path }}</p>
                        </div>
                        <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                          {{ file.name.split('.').pop()?.toUpperCase() }}
                        </span>
                      </div>
                    </button>
                  </div>

                  <div v-if="filteredMsfFiles.length > 0" class="mt-4 flex flex-col gap-3 border-t border-gray-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <p class="text-xs text-gray-500">
                      Page {{ msfPage }} of {{ totalMsfPages }} · showing {{ visibleMsfFiles.length }} file{{ visibleMsfFiles.length === 1 ? '' : 's' }} on this page
                    </p>
                    <div class="flex gap-2">
                      <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                        :disabled="msfPage <= 1"
                        @click="goToPreviousMsfPage"
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                        :disabled="msfPage >= totalMsfPages"
                        @click="goToNextMsfPage"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                </div>
                <p v-if="!loadingLocalMsf && availableMsfFiles.length === 0" class="mt-1 text-xs text-red-500">
                  No MSF (.xlsx/.xls/.csv) files found in the configured {{ localScanLabel.toLowerCase() }} input directory.
                </p>
                <p class="mt-2 text-xs text-gray-500">
                  {{ msfScanScopeDescription }}
                </p>
              </div>

              <div class="flex items-center space-x-4">
                <button
                  @click="preflightLocalMsf"
                  :disabled="!selectedMsfPath || localMsfPreflighting"
                  class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {{ localMsfPreflighting ? 'Preflighting...' : 'Preflight MSF' }}
                </button>
                <span v-if="localMsfPreflightResult" class="text-sm">
                  <span v-if="localMsfPreflightResult.is_valid" class="text-green-600 font-medium">
                    ✓ Preflight passed
                  </span>
                  <span v-else class="text-red-600 font-medium">
                    ✗ Preflight failed
                  </span>
                </span>
              </div>

              <div v-if="localMsfPreflightResult" class="bg-gray-50 rounded-lg p-4 space-y-2">
                <h4 class="font-medium text-gray-900">Local MSF Preflight</h4>
                <p class="text-sm text-gray-600">
                  Duplicate policy: <span class="font-mono">merge_non_empty</span> (auto-patch at submit)
                </p>
                <p class="text-sm text-gray-600">
                  Filename cells normalized: {{ localMsfPreflightResult.summary?.filename_cells_normalized || 0 }},
                  duplicate groups: {{ localMsfPreflightResult.summary?.duplicate_groups_detected || 0 }}
                </p>
                <p v-if="localPreflightValidation.filename_column" class="text-sm text-gray-600">
                  Filename column: <span class="font-mono">{{ localPreflightValidation.filename_column }}</span>
                  <span>
                    ({{ Math.round(localFilenameDetectionConfidence * 100) }}% confidence)
                  </span>
                </p>
                <p
                  v-for="msg in localPreflightBlockers"
                  :key="`blocker-${msg}`"
                  class="text-sm text-red-600"
                >
                  ✗ {{ msg }}
                </p>
                <p
                  v-for="msg in localPreflightWarnings"
                  :key="`warn-${msg}`"
                  class="text-sm text-amber-600"
                >
                  ⚠ {{ msg }}
                </p>
                <div class="mt-3 rounded-md border border-indigo-200 bg-indigo-50 p-3">
                  <p class="text-sm font-medium text-indigo-900">
                    {{ localMsfPreflightResult.is_valid ? 'Next step' : 'How to fix this' }}
                  </p>
                  <p class="mt-1 text-sm text-indigo-800">
                    {{ localMsfPreflightResult.is_valid
                      ? 'Continue to the Guided MSF Repair step to inspect the row-level analysis before the real directory scan starts.'
                      : 'You can continue even with blockers. The next step shows row-level problems, explains why they break EDM / IIIF / METS generation, and offers direct repairs where possible.' }}
                  </p>
                  <ul v-if="localPreflightGuidance.length" class="mt-2 space-y-1 text-sm text-indigo-900">
                    <li v-for="hint in localPreflightGuidance" :key="hint">• {{ hint }}</li>
                  </ul>
                </div>

                <div v-if="localDuplicateDirectoryDetails.length" class="mt-3 rounded-md border border-red-200 bg-red-50 p-3">
                  <p class="text-sm font-medium text-red-800">Conflicting file paths</p>
                  <div
                    v-for="detail in localDuplicateDirectoryDetails.slice(0, 6)"
                    :key="`conflict-${detail.basename}`"
                    class="mt-2 rounded-md border border-red-100 bg-white p-3"
                  >
                    <p class="text-xs font-semibold text-gray-900">{{ detail.basename }}</p>
                    <ul class="mt-1 space-y-1 text-xs text-gray-600">
                      <li v-for="path in detail.paths" :key="`${detail.basename}-${path}`">{{ path }}</li>
                    </ul>
                    <div v-if="detail.suggested_directories?.length" class="mt-2 flex flex-wrap gap-2">
                      <button
                        v-for="suggested in detail.suggested_directories"
                        :key="`${detail.basename}-${suggested}`"
                        type="button"
                        class="px-2.5 py-1 text-xs font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100"
                        @click="applySuggestedLocalDirectory(suggested)"
                      >
                        Select {{ suggested }}
                      </button>
                    </div>
                  </div>
                  <div v-if="localSuggestedDirectories.length" class="mt-3 flex flex-wrap gap-2">
                    <button
                      v-for="suggested in localSuggestedDirectories"
                      :key="`global-suggested-${suggested}`"
                      type="button"
                      class="px-3 py-1.5 text-xs font-medium text-indigo-700 bg-white border border-indigo-200 rounded-md hover:bg-indigo-50"
                      @click="applySuggestedLocalDirectory(suggested)"
                    >
                      Try narrower directory: {{ suggested }}
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="recordResolutionLoading" class="rounded-lg border border-sky-200 bg-sky-50 px-4 py-4 text-sm text-sky-900">
                Preparing the record-resolution analysis for this {{ batchPreparationLabel }}...
              </div>

              <RecordResolutionReview
                v-else-if="recordResolutionAnalysis"
                :analysis="recordResolutionAnalysis"
                :loading="recordResolutionLoading"
                :saving="recordResolutionSaving"
                @policy-change="handleRecordResolutionPolicyChange"
                @save-decisions="handleRecordResolutionSave"
              />
            </div>

            <!-- Standard MSF File Upload (Hidden in Local Mode) -->
            <div v-else>
              <label class="block text-sm font-medium text-gray-700 mb-2">
                Metadata Source File (MSF) <span class="text-red-500">*</span>
              </label>

              <!-- File Upload Zone -->
              <div
                @drop.prevent="handleMsfDrop"
                @dragover.prevent="isMsfDragging = true"
                @dragleave.prevent="isMsfDragging = false"
                :class="[
                  'border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer focus-within:ring-2 focus-within:ring-indigo-500',
                  isMsfDragging ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300 hover:border-gray-400'
                ]"
                @click="$refs.msfFileInput.click()"
              >
                <input
                  ref="msfFileInput"
                  data-testid="upload-msf-input"
                  aria-label="Metadata source file"
                  type="file"
                  class="sr-only"
                  @click.stop
                  accept=".xlsx,.xls,.csv"
                  @change="handleMsfFileSelect"
                />

                <div v-if="!msfFile" class="space-y-2">
                  <svg class="mx-auto h-10 w-10 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p class="text-sm text-gray-600">
                    <span class="text-indigo-600 font-medium">Click to select</span> or drag and drop
                  </p>
                  <p class="text-xs text-gray-500">Excel (.xlsx) or CSV files only</p>
                </div>

                <div v-else class="flex items-center justify-center space-x-3">
                  <svg class="h-8 w-8 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                  </svg>
                  <div class="text-left">
                    <p class="text-sm font-medium text-gray-900">{{ msfFile.name }}</p>
                    <p class="text-xs text-gray-500">{{ formatFileSize(msfFile.size) }}</p>
                  </div>
                  <button
                    aria-label="Remove metadata file"
                    @click.stop="removeMsfFile"
                    class="text-red-500 hover:text-red-700"
                    title="Remove file"
                  >
                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                  </button>
                </div>
              </div>

              <!-- Upload status -->
              <p v-if="uploadingMsf" class="mt-2 text-sm text-indigo-600">
                Uploading MSF file...
              </p>
              <p v-else-if="msfPath" class="mt-2 text-sm text-green-600">
                ✓ MSF file uploaded and ready
              </p>
            </div>

            <div v-if="isCsvMsfSelected" class="rounded-md border border-blue-200 bg-blue-50 p-3">
              <label class="inline-flex items-center gap-2 text-sm text-blue-900">
                <input
                  v-model="useFirstRowAsHeader"
                  type="checkbox"
                  @change="csvHeaderPreferenceTouched = true"
                  class="rounded border-blue-300 text-indigo-600 focus:ring-indigo-500"
                >
                Use first row as headers?
              </label>
              <p class="mt-1 text-xs text-blue-700">
                Disable this when the CSV has no header row; column names will be inferred automatically.
              </p>
            </div>

            <!-- Validate MSF Button (Only for Upload Mode) -->
            <div v-if="storageStatus?.mode !== 'local'" class="flex items-center space-x-4">
              <button
                @click="validateMsf"
                :disabled="!canValidateMsf || validatingMsf"
                data-testid="upload-validate-msf"
                class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {{ validatingMsf ? 'Validating...' : 'Validate MSF' }}
              </button>
              <span v-if="msfValidationResult" class="text-sm">
                <span v-if="msfValidationResult.is_valid" class="text-green-600 font-medium">
                  ✓ {{ msfValidationResult.matched_count }} files matched
                </span>
                <span v-else class="text-red-600 font-medium">
                  ✗ Validation failed
                </span>
              </span>
            </div>

            <!-- MSF Validation Results -->
            <div
              v-if="storageStatus?.mode !== 'local' && zipMsfPreflightReport"
              data-testid="upload-msf-preflight"
              class="bg-indigo-50 border border-indigo-200 rounded-lg p-4 space-y-3"
            >
              <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h4 class="font-medium text-indigo-950">MSF Preflight Repair</h4>
                  <p class="mt-1 text-sm text-indigo-800">
                    The uploaded MSF was checked against the ZIP before the batch session was created.
                  </p>
                </div>
                <span
                  class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium"
                  :class="zipMsfPreflightReport.is_valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'"
                >
                  {{ zipMsfPreflightReport.is_valid ? 'Passed' : 'Needs review' }}
                </span>
              </div>

              <dl class="grid gap-3 sm:grid-cols-4">
                <div class="rounded-md bg-white/80 p-3">
                  <dt class="text-xs font-medium uppercase tracking-wide text-indigo-700">Normalized</dt>
                  <dd class="mt-1 text-lg font-semibold text-indigo-950">{{ zipMsfPreflightSummary.filename_cells_normalized || 0 }}</dd>
                </div>
                <div class="rounded-md bg-white/80 p-3">
                  <dt class="text-xs font-medium uppercase tracking-wide text-indigo-700">References repaired</dt>
                  <dd class="mt-1 text-lg font-semibold text-indigo-950">{{ zipMsfPreflightSummary.filename_references_repaired || 0 }}</dd>
                </div>
                <div class="rounded-md bg-white/80 p-3">
                  <dt class="text-xs font-medium uppercase tracking-wide text-indigo-700">Duplicates merged</dt>
                  <dd class="mt-1 text-lg font-semibold text-indigo-950">{{ zipMsfPreflightSummary.duplicate_rows_merged || 0 }}</dd>
                </div>
                <div class="rounded-md bg-white/80 p-3">
                  <dt class="text-xs font-medium uppercase tracking-wide text-indigo-700">Rows after patch</dt>
                  <dd class="mt-1 text-lg font-semibold text-indigo-950">{{ zipMsfPreflightSummary.rows_after_patch || 0 }}</dd>
                </div>
              </dl>

              <div v-if="zipMsfPreflightActions.length">
                <p class="text-sm font-medium text-indigo-900">Applied repair actions</p>
                <ul class="mt-2 space-y-1 text-sm text-indigo-900">
                  <li v-for="action in zipMsfPreflightActions" :key="action" class="flex gap-2">
                    <span class="text-green-600">✓</span>
                    <span>{{ action }}</span>
                  </li>
                </ul>
              </div>

              <div v-if="zipMsfPreflightReport.warnings?.length">
                <p
                  v-for="warning in zipMsfPreflightReport.warnings"
                  :key="`preflight-warning-${warning}`"
                  class="text-sm text-amber-700"
                >
                  ⚠ {{ warning }}
                </p>
              </div>
            </div>

            <div v-if="msfValidationResult" class="bg-gray-50 rounded-lg p-4 space-y-4">
              <h4 class="font-medium text-gray-900">MSF Validation Results</h4>

              <!-- Matched Files -->
              <div v-if="msfValidationResult.matched_files?.length > 0">
                <p class="text-sm font-medium text-green-700 mb-2">
                  ✓ Matched Files ({{ msfValidationResult.matched_count }})
                </p>
                <ul class="text-sm text-gray-600 space-y-1 max-h-32 overflow-y-auto">
                  <li v-for="file in msfValidationResult.matched_files" :key="file" class="flex items-center">
                    <svg class="h-4 w-4 text-green-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                    </svg>
                    {{ file }}
                  </li>
                </ul>
              </div>

              <!-- Missing Files (in MSF but not in directory) -->
              <div v-if="msfValidationResult.missing_files?.length > 0">
                <p class="text-sm font-medium text-amber-700 mb-2">
                  ⚠ Files in MSF but not in directory ({{ msfValidationResult.missing_count }})
                </p>
                <ul class="text-sm text-gray-600 space-y-1">
                  <li v-for="file in msfValidationResult.missing_files" :key="file" class="flex items-center">
                    <svg class="h-4 w-4 text-amber-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                    </svg>
                    {{ file }}
                  </li>
                </ul>
              </div>

              <!-- Implicit Dependencies (referenced by matched files) -->
              <div v-if="msfValidationResult.implicitly_included_files?.length > 0">
                <p class="text-sm font-medium text-indigo-700 mb-2">
                  ✓ Referenced dependency files included automatically ({{ msfValidationResult.implicitly_included_count || msfValidationResult.implicitly_included_files.length }})
                </p>
                <ul class="text-sm text-gray-600 space-y-1 max-h-32 overflow-y-auto">
                  <li v-for="file in msfValidationResult.implicitly_included_files" :key="`implicit-${file}`" class="flex items-center">
                    <svg class="h-4 w-4 text-indigo-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                    </svg>
                    {{ file }}
                  </li>
                </ul>
              </div>

              <!-- Unmapped Files (in directory but not in MSF) -->
              <div v-if="msfValidationResult.unmapped_files?.length > 0">
                <p class="text-sm font-medium text-gray-500 mb-2">
                  ℹ Files in directory but not in MSF (will be excluded) ({{ msfValidationResult.unmapped_count }})
                </p>
                <ul class="text-sm text-gray-500 space-y-1">
                  <li v-for="file in msfValidationResult.unmapped_files" :key="file">
                    {{ file }}
                  </li>
                </ul>
              </div>

              <!-- Warnings -->
              <div v-if="msfValidationResult.warnings?.length > 0">
                <p class="text-sm text-amber-600" v-for="warning in msfValidationResult.warnings" :key="warning">
                  ⚠ {{ warning }}
                </p>
              </div>
            </div>

            <div
              v-if="storageStatus?.mode !== 'local' && recordResolutionLoading"
              class="rounded-lg border border-sky-200 bg-sky-50 px-4 py-4 text-sm text-sky-900"
            >
              Preparing the record-resolution analysis for this batch session...
            </div>

            <RecordResolutionReview
              v-else-if="storageStatus?.mode !== 'local' && recordResolutionAnalysis"
              :analysis="recordResolutionAnalysis"
              :loading="recordResolutionLoading"
              :saving="recordResolutionSaving"
              @policy-change="handleRecordResolutionPolicyChange"
              @save-decisions="handleRecordResolutionSave"
            />
          </div>
        </div>

        </fieldset>

        <!-- Error Message -->
        <div v-if="error" data-testid="upload-error" role="alert" class="mt-4 bg-red-50 border border-red-400 text-red-700 px-4 py-3 rounded">
          <p>{{ error }}</p>
          <button v-if="hasFailures"
                  @click="handleResume"
                  class="mt-2 text-sm font-bold underline hover:text-red-900 focus:outline-none">
             Resume / Retry Failed Files
          </button>
        </div>

        <!-- Success Message -->
        <div v-if="success" role="status" class="mt-4 bg-green-50 border border-green-400 text-green-700 px-4 py-3 rounded">
          {{ success }}
        </div>

        <div v-if="uploading" class="mt-6 rounded-lg border border-indigo-100 bg-indigo-50 p-4" aria-busy="true">
          <ProgressBar :percentage="visibleUploadPercent" :label="uploadProgressLabel" />
          <p class="mt-3 text-sm text-gray-600" role="status">{{ uploadStatusMessage || 'Keep this page open while your files are transferred and checked.' }}</p>
          <p v-if="uploadMonitorUnavailable" role="status" class="mt-3 text-sm text-amber-800">
            Progress updates are temporarily unavailable. Your upload may still be running. Reconnecting automatically…
          </p>
          <router-link v-if="uploadMode === 'directory' && workflowStore.sessionId" :to="`/uploads/${workflowStore.sessionId}`" class="mt-3 inline-block text-sm font-medium text-indigo-700 underline">
            Open upload monitor
          </router-link>
        </div>

        <div class="mt-6 rounded-2xl border border-gray-200 bg-gray-50 p-5">
          <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-gray-900">Ready to continue?</p>
              <p class="mt-1 text-sm text-gray-600">
                Check your selection before continuing.
              </p>
              <ul class="mt-4 space-y-3">
                <li
                  v-for="item in uploadReadinessItems"
                  :key="item.label"
                  class="flex items-start gap-3"
                >
                  <span
                    class="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold"
                    :class="item.ready ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'"
                  >
                    {{ item.ready ? '✓' : '!' }}
                  </span>
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-gray-900">{{ item.label }}</p>
                    <p class="mt-0.5 text-sm text-gray-600">{{ item.detail }}</p>
                  </div>
                </li>
              </ul>
              <p v-if="uploadBlockingMessage" id="upload-blocking-message" class="mt-4 text-sm text-amber-700">
                {{ uploadBlockingMessage }}
              </p>
            </div>

            <div class="lg:w-72 lg:flex-shrink-0">
              <button
                @click="handleUpload"
                :disabled="!canUpload || uploading"
                data-testid="upload-primary-action"
                :aria-describedby="uploadBlockingMessage ? 'upload-blocking-message' : undefined"
                class="w-full px-6 py-3 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {{ localContinueLabel }}
              </button>
              <p class="mt-3 text-xs text-gray-500">
                {{ uploadCtaHelp }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useWorkflowStore } from '@/stores/workflow'
import fileService from '@/services/file.service'
import api from '@/services/api'
import msfService from '@/services/msf.service'
import submissionService from '@/services/submission.service'
import hpcLinkService from '@/services/hpcLink.service'
import RecordResolutionReview from '@/components/workflow/RecordResolutionReview.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()
const authStore = useAuthStore()
const workflowStore = useWorkflowStore()

const workspaceType = ref(authStore.institutions.length ? (authStore.user?.default_institution_id ? 'institution' : 'personal') : 'personal')
const selectedInstitutionId = ref(authStore.user?.default_institution_id || '')
const sharingScope = ref(authStore.user?.default_institution_id ? 'institution' : 'private')
const credentialPreference = ref(authStore.user?.default_institution_id ? 'institution' : 'user')
const defaultZenodoEnvironment = ref('sandbox')
const useInstitutionDefaultCommunities = ref(Boolean(authStore.user?.default_institution_id))
const institutionWorkspaceOptions = computed(() => authStore.institutions || [])

watch(workspaceType, (nextType) => {
  if (nextType === 'institution' && institutionWorkspaceOptions.value.length > 0) {
    if (!selectedInstitutionId.value) {
      selectedInstitutionId.value = institutionWorkspaceOptions.value[0].id
    }
    sharingScope.value = 'institution'
    credentialPreference.value = 'institution'
    useInstitutionDefaultCommunities.value = true
    return
  }
  sharingScope.value = 'private'
  credentialPreference.value = 'user'
  useInstitutionDefaultCommunities.value = false
})

watch(
  institutionWorkspaceOptions,
  (nextInstitutions) => {
    if (!nextInstitutions.length) {
      workspaceType.value = 'personal'
      selectedInstitutionId.value = ''
      return
    }
    const match = nextInstitutions.find((entry) => entry.id === selectedInstitutionId.value)
    if (!match) {
      selectedInstitutionId.value = authStore.user?.default_institution_id || nextInstitutions[0].id
    }
  },
  { immediate: true }
)

const selectedWorkspaceInstitution = computed(() => {
  return institutionWorkspaceOptions.value.find((entry) => entry.id === selectedInstitutionId.value) || null
})

const buildWorkspacePayload = () => {
  const payload = {
    sharing_scope: sharingScope.value,
    credential_preference: credentialPreference.value,
    default_zenodo_environment: defaultZenodoEnvironment.value,
  }
  if (workspaceType.value === 'institution' && selectedInstitutionId.value) {
    payload.institution_id = selectedInstitutionId.value
    payload.use_institution_default_communities = useInstitutionDefaultCommunities.value
  }
  return payload
}

const uploadMode = ref('file')
const selectedFiles = ref([])

// ZIP Mode State
const zipFile = ref(null)
const zipPath = ref('') // Server-side path after temp upload if any
const isZipDragging = ref(false)

// MSF State
const msfFile = ref(null)
const msfPath = ref('')    // Server-side path after upload
const isMsfDragging = ref(false)
const selectedMsfPath = ref('')
const availableMsfFiles = ref([])
const availableLocalSubdirectories = ref([])
const localInputRoot = ref('')
const directoryPath = ref('')
const directorySearchQuery = ref('')
const directoryPage = ref(1)
const msfSearchQuery = ref('')
const msfPage = ref(1)
const loadingLocalMsf = ref(false)
const localMsfPreflighting = ref(false)
const localMsfPreflightResult = ref(null)
const recordResolutionLoading = ref(false)
const recordResolutionSaving = ref(false)
const recordResolutionAnalysis = ref(null)
const preparedBatchSessionId = ref(null)
const preparedBatchProfile = ref(null)
const useFirstRowAsHeader = ref(true)
const csvHeaderPreferenceTouched = ref(false)

// UI State
const isDragging = ref(false)
const uploading = ref(false)
const uploadingMsf = ref(false)
const uploadingZip = ref(false)
const validatingMsf = ref(false)
const error = ref('')
const success = ref('')
const msfValidationResult = ref(null)
const zipMsfPreflightReport = ref(null)
const hpcStatus = ref(null)
const hpcAllocation = ref(null)
const hpcAllocationLoading = ref(false)
const hpcAllocationError = ref('')

// Upload progress stage (0=not started, 1=extracting, 2=processing, 3=cloud upload, 4=complete)
const uploadStage = ref(0)

// Storage status state
const storageStatus = ref(null)
const isConnecting = ref(false)

const hpcStatusMessage = computed(() => {
  if (!hpcStatus.value) {
    return 'Checking whether this WebHDP instance can allocate external HPC resources.'
  }
  if (hpcStatus.value.deployment_class === 'workstation-local' && !hpcStatus.value.available) {
    return 'This workstation-local deployment can use local HDP Component services without HPC-Link.'
  }
  if (!hpcStatus.value.available) {
    return 'HPC-Link is not enabled on this WebHDP instance. Server/VPS deployments require HPC-Link for compute-heavy HDP Components.'
  }
  if (!hpcStatus.value.can_allocate) {
    return hpcStatus.value.permission_reason || 'Your account is not allowed to allocate HPC resources.'
  }
  if (!workflowStore.sessionId) {
    return 'HPC-Link connects WebHDP to a remote compute cluster for rendering. Request resources here when you are ready to use them.'
  }
  return 'Request compute time for this session before running the renderer. The final review checks that the required services are ready.'
})

const showHpcResourcePanel = computed(() => {
  if (!hpcStatus.value) return true
  if (hpcStatus.value.deployment_class === 'workstation-local' && !hpcStatus.value.available) {
    return false
  }
  return true
})

const isWorkstationLocalDeployment = computed(() => (
  hpcStatus.value?.deployment_class === 'workstation-local'
))

const localScanLabel = computed(() => (
  isWorkstationLocalDeployment.value ? 'Local Folder' : 'Server/HPC Directory'
))

const directorySearchPlaceholder = computed(() => (
  isWorkstationLocalDeployment.value
    ? 'Filter nested local folders by name or path'
    : 'Filter nested server/HPC directories by name or path'
))

const msfScanScopeDescription = computed(() => (
  isWorkstationLocalDeployment.value
    ? 'The system scans for model files matching the metadata in this file inside the selected local folder.'
    : 'The system scans for model files matching the metadata in this file inside the selected server/HPC directory.'
))

const attachedFilesystemMirrorMessage = computed(() => (
  isWorkstationLocalDeployment.value
    ? 'Bypassing cloud storage. Mirroring directly to local workstation output storage.'
    : 'Bypassing cloud storage. Mirroring directly to attached server/HPC output storage.'
))

const batchPreparationLabel = computed(() => (
  isWorkstationLocalDeployment.value ? 'local workstation batch session' : 'server/HPC batch session'
))

const hpcAllocationButtonLabel = computed(() => {
  if (hpcAllocationLoading.value) return 'Requesting...'
  if (hpcAllocation.value?.status === 'running') return 'Allocation active'
  if (hpcAllocation.value?.status === 'queued') return 'Queued'
  if (hpcAllocation.value?.status === 'allocating') return 'Allocating'
  return 'Request HPC resources'
})

const DIRECTORY_UPLOAD_STATE_KEY = 'directory_upload_state_v1'
const DIRECTORY_PAGE_SIZE = 15
const MSF_PAGE_SIZE = 10

const readDirectoryUploadState = () => {
  const raw = sessionStorage.getItem(DIRECTORY_UPLOAD_STATE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch (e) {
    console.warn('Failed to parse saved directory upload state:', e)
    sessionStorage.removeItem(DIRECTORY_UPLOAD_STATE_KEY)
    return null
  }
}

const writeDirectoryUploadState = (state) => {
  if (!state) {
    sessionStorage.removeItem(DIRECTORY_UPLOAD_STATE_KEY)
    return
  }
  sessionStorage.setItem(DIRECTORY_UPLOAD_STATE_KEY, JSON.stringify(state))
}

const clearDirectoryUploadState = () => {
  sessionStorage.removeItem(DIRECTORY_UPLOAD_STATE_KEY)
}

const createSubmitToken = () => {
  if (window.crypto?.randomUUID) {
    return `upl_${window.crypto.randomUUID()}`
  }
  return `upl_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

const buildDirectoryFingerprint = () => {
  return JSON.stringify({
    mode: storageStatus.value?.mode || '',
    zip_name: zipFile.value?.name || '',
    zip_size: zipFile.value?.size || 0,
    msf_name: msfFile.value?.name || '',
    msf_path: selectedMsfPath.value || '',
    parse_options: buildMsfParseOptionsPayload()
  })
}

const ensureDirectorySubmitState = () => {
  const fingerprint = buildDirectoryFingerprint()
  const existing = readDirectoryUploadState()
  if (existing?.submit_token && existing?.fingerprint === fingerprint) {
    return existing
  }

  const next = {
    submit_token: createSubmitToken(),
    fingerprint,
    created_at: new Date().toISOString(),
    session_id: null,
    task_id: null
  }
  writeDirectoryUploadState(next)
  return next
}

const persistDirectorySubmitContext = ({ submitToken, sessionId, taskId }) => {
  const existing = readDirectoryUploadState() || {}
  writeDirectoryUploadState({
    ...existing,
    submit_token: submitToken || existing.submit_token || null,
    session_id: sessionId ?? existing.session_id ?? null,
    task_id: taskId ?? existing.task_id ?? null,
    updated_at: new Date().toISOString()
  })
}

const recoverDirectorySubmission = async (submitToken) => {
  if (!submitToken) return null
  const recovered = await api.post(
    '/sessions/directory/recover',
    { submit_token: submitToken },
    { suppressGlobalError: true }
  )
  return recovered?.data || null
}

// Fetch storage status when switching to directory mode
const fetchStorageStatus = async () => {
  isConnecting.value = true
  try {
    const response = await api.get('/admin/storage-status')
    storageStatus.value = {
      available: response.data.active_storage !== null,
      type: response.data.active_storage,
      mode: response.data.config?.storage_mode,
      message: response.data.active_message
    }

    // If in local mode, fetch available MSF files
    if (storageStatus.value.mode === 'local') {
      msfFile.value = null
      msfValidationResult.value = null
      localMsfPreflightResult.value = null
      resetRecordResolutionAnalysis()
      fetchLocalMsfFiles()
    } else {
      selectedMsfPath.value = ''
      localInputRoot.value = ''
      localMsfPreflightResult.value = null
      resetRecordResolutionAnalysis()
    }
  } catch (err) {
    console.error('Failed to fetch storage status:', err)
    storageStatus.value = {
      available: false,
      type: null,
      mode: null,
      message: 'Could not check storage status'
    }
  } finally {
    isConnecting.value = false
  }
}

const fetchLocalMsfFiles = async () => {
  loadingLocalMsf.value = true
  try {
    const response = await api.get('/sessions/local-msf')
    availableMsfFiles.value = response.data.msf_files || []
    availableLocalSubdirectories.value = response.data.subdirectories || []
    localInputRoot.value = response.data.input_root || ''
    directoryPage.value = 1
    msfPage.value = 1
    const hasCurrentDirectory = availableLocalSubdirectories.value.some(
      entry => entry?.relative_path === directoryPath.value
    )
    if (!hasCurrentDirectory) {
      directoryPath.value = ''
    }
  } catch (err) {
    console.error('Failed to fetch local MSF files:', err)
    error.value = 'Failed to load available MSF files from server.'
  } finally {
    loadingLocalMsf.value = false
  }
}

const buildDirectorySearchValue = (entry) => {
  return `${entry?.relative_path || ''} ${entry?.name || ''}`.toLowerCase()
}

const filteredLocalSubdirectories = computed(() => {
  const query = directorySearchQuery.value.trim().toLowerCase()
  const tokens = query.split(/\s+/).filter(Boolean)
  if (!tokens.length) {
    return availableLocalSubdirectories.value
  }
  return availableLocalSubdirectories.value.filter(entry => {
    const haystack = buildDirectorySearchValue(entry)
    return tokens.every(token => haystack.includes(token))
  })
})

const totalDirectoryPages = computed(() => {
  return Math.max(1, Math.ceil(filteredLocalSubdirectories.value.length / DIRECTORY_PAGE_SIZE))
})

const visibleLocalSubdirectories = computed(() => {
  const start = (directoryPage.value - 1) * DIRECTORY_PAGE_SIZE
  return filteredLocalSubdirectories.value.slice(start, start + DIRECTORY_PAGE_SIZE)
})

const selectedLocalDirectory = computed(() => {
  if (!directoryPath.value) return null
  return availableLocalSubdirectories.value.find(entry => entry?.relative_path === directoryPath.value) || null
})

const selectLocalDirectory = (relativePath) => {
  directoryPath.value = relativePath || ''
}

const buildMsfSearchValue = (file) => {
  return `${file?.name || ''} ${file?.path || ''}`.toLowerCase()
}

const filteredMsfFiles = computed(() => {
  const query = msfSearchQuery.value.trim().toLowerCase()
  const tokens = query.split(/\s+/).filter(Boolean)
  if (!tokens.length) {
    return availableMsfFiles.value
  }
  return availableMsfFiles.value.filter(file => {
    const haystack = buildMsfSearchValue(file)
    return tokens.every(token => haystack.includes(token))
  })
})

const totalMsfPages = computed(() => {
  return Math.max(1, Math.ceil(filteredMsfFiles.value.length / MSF_PAGE_SIZE))
})

const visibleMsfFiles = computed(() => {
  const start = (msfPage.value - 1) * MSF_PAGE_SIZE
  return filteredMsfFiles.value.slice(start, start + MSF_PAGE_SIZE)
})

const selectedMsfFileEntry = computed(() => {
  if (!selectedMsfPath.value) return null
  return availableMsfFiles.value.find(file => (file.full_path || file.path) === selectedMsfPath.value) || null
})

const selectMsfFile = (file) => {
  selectedMsfPath.value = file?.full_path || file?.path || ''
}

const goToPreviousDirectoryPage = () => {
  if (directoryPage.value > 1) {
    directoryPage.value -= 1
  }
}

const goToNextDirectoryPage = () => {
  if (directoryPage.value < totalDirectoryPages.value) {
    directoryPage.value += 1
  }
}

const goToPreviousMsfPage = () => {
  if (msfPage.value > 1) {
    msfPage.value -= 1
  }
}

const goToNextMsfPage = () => {
  if (msfPage.value < totalMsfPages.value) {
    msfPage.value += 1
  }
}

const attachedFilesystemLabel = computed(() => (
  isWorkstationLocalDeployment.value
    ? 'Local Folder Storage'
    : 'Server/HPC Filesystem Storage'
))

// Helper to format storage type names
const formatStorageType = (type) => {
  const types = {
    dropbox: 'Dropbox',
    gdrive: 'Google Drive',
    server: storageStatus.value?.mode === 'local' ? attachedFilesystemLabel.value : 'Server Storage'
  }
  return types[type] || type || 'None'
}

// Helper to format storage mode names
const formatStorageMode = (mode) => {
  const modes = {
    pure_cloud: 'Pure Cloud',
    cloud_backup: 'Cloud Backup',
    server_only: 'Server Only',
    local: isWorkstationLocalDeployment.value ? 'Local Workstation' : 'Server/HPC Filesystem'
  }
  return modes[mode] || mode || 'Unknown'
}

const selectUploadPath = (mode) => {
  if (uploading.value || validatingMsf.value) return
  uploadMode.value = mode
  error.value = ''
  success.value = ''
  if (mode !== 'directory') {
    resetRecordResolutionAnalysis()
  }
}

const uploadPathSummary = computed(() => {
  if (uploadMode.value === 'file') {
    return {
      title: 'Manual upload path',
      description: 'Upload one file directly, then continue to file review. No MSF validation is required in this path.',
    }
  }

  if (storageStatus.value?.mode === 'local') {
    const localLabel = isWorkstationLocalDeployment.value ? 'local folder' : 'server/HPC directory'
    return {
      title: `${localLabel.charAt(0).toUpperCase()}${localLabel.slice(1)} scan path`,
      description: `Choose an MSF and a ${localLabel}. The system runs a local preflight first, then opens guided MSF repair before the real scan starts.`,
    }
  }

  return {
    title: 'ZIP + MSF validation path',
    description: 'Upload a ZIP with model files and a matching MSF. Validate them together before entering the batch workflow.',
  }
})

const uploadStepHint = computed(() => {
  if (uploadMode.value === 'file') {
    return 'Choose one file to create a session. Next you will review it and add descriptions. Uploading does not publish anything.'
  }
  if (storageStatus.value?.mode === 'local') {
    const localLabel = isWorkstationLocalDeployment.value ? 'local folder' : 'server/HPC directory'
    return `Choose the ${localLabel} and MSF, run preflight, then continue into guided MSF repair before the real scan starts.`
  }
  return 'Upload a ZIP and an MSF, validate the file-to-row matches, then continue into the batch workflow.'
})

// Watch for upload mode changes
watch(uploadMode, (newMode) => {
  if (newMode === 'directory') {
    fetchStorageStatus()
  }
})

watch(directorySearchQuery, () => {
  directoryPage.value = 1
})

watch(filteredLocalSubdirectories, () => {
  if (directoryPage.value > totalDirectoryPages.value) {
    directoryPage.value = totalDirectoryPages.value
  }
})

watch(msfSearchQuery, () => {
  msfPage.value = 1
})

watch(filteredMsfFiles, () => {
  if (msfPage.value > totalMsfPages.value) {
    msfPage.value = totalMsfPages.value
  }
})

const resetRecordResolutionAnalysis = () => {
  recordResolutionAnalysis.value = null
  preparedBatchSessionId.value = null
  preparedBatchProfile.value = null
}

const loadRecordResolutionAnalysis = async (sessionId, payload = null) => {
  if (!sessionId) {
    recordResolutionAnalysis.value = null
    return null
  }
  recordResolutionLoading.value = true
  try {
    const response = payload
      ? await submissionService.analyzeSessionRecordResolution(sessionId, payload)
      : await submissionService.getSessionRecordResolution(sessionId)
    recordResolutionAnalysis.value = response.data || null
    return recordResolutionAnalysis.value
  } finally {
    recordResolutionLoading.value = false
  }
}

const handleRecordResolutionPolicyChange = async (policyPreset) => {
  if (!preparedBatchSessionId.value) return
  try {
    await loadRecordResolutionAnalysis(preparedBatchSessionId.value, { policy_override: policyPreset })
    toast.success('Record-resolution policy updated for this session.')
  } catch (err) {
    console.error('Failed to update record-resolution policy:', err)
    toast.error(err?.error?.message || err?.message || 'Failed to update the record-resolution policy.')
  }
}

const handleRecordResolutionSave = async (payload) => {
  if (!preparedBatchSessionId.value) return
  recordResolutionSaving.value = true
  try {
    const response = await submissionService.updateSessionRecordResolution(preparedBatchSessionId.value, payload)
    recordResolutionAnalysis.value = response.data || null
  } catch (err) {
    console.error('Failed to save record-resolution decisions:', err)
    toast.error(err?.error?.message || err?.message || 'Failed to save the record-resolution decisions.')
  } finally {
    recordResolutionSaving.value = false
  }
}

watch(selectedMsfPath, async (newPath) => {
  if (storageStatus.value?.mode !== 'local') return
  resetRecordResolutionAnalysis()
  localMsfPreflightResult.value = null
  if (!newPath) return
  await preflightLocalMsf()
})

watch(directoryPath, async () => {
  if (storageStatus.value?.mode !== 'local') return
  resetRecordResolutionAnalysis()
  if (!selectedMsfPath.value) return
  await preflightLocalMsf()
})

const canValidateMsf = computed(() => {
  return zipFile.value && msfFile.value
})

const localPreflightValidation = computed(() => localMsfPreflightResult.value?.validation || {})
const localPreflightBlockers = computed(() => localMsfPreflightResult.value?.blockers || [])
const localPreflightWarnings = computed(() => localMsfPreflightResult.value?.warnings || [])
const localDuplicateDirectoryFiles = computed(() => localPreflightValidation.value?.duplicate_directory_files || [])
const localDuplicateDirectoryDetails = computed(() => localPreflightValidation.value?.duplicate_directory_details || [])
const zipMsfPreflightSummary = computed(() => zipMsfPreflightReport.value?.summary || {})
const zipMsfPreflightActions = computed(() => {
  const actions = zipMsfPreflightReport.value?.actions || []
  return actions.map((action) => (
    String(action || '').startsWith('Wrote patched MSF')
      ? 'Prepared patched MSF for processing.'
      : action
  ))
})
const localSuggestedDirectories = computed(() => {
  return Array.from(
    new Set(
      localDuplicateDirectoryDetails.value.flatMap(detail => detail.suggested_directories || [])
    )
  ).sort((a, b) => a.localeCompare(b))
})
const localFilenameDetectionConfidence = computed(() => Number(localPreflightValidation.value?.filename_detection_confidence || 0))
const localHasLowFilenameConfidence = computed(() => {
  const confidence = localFilenameDetectionConfidence.value
  return localPreflightValidation.value?.filename_column && confidence < 0.3
})
const localPreflightGuidance = computed(() => {
  const hints = []
  if (localDuplicateDirectoryFiles.value.length) {
    hints.push(
      `The selected target directory contains duplicate basenames. Choose a narrower directory or rename the conflicting ${isWorkstationLocalDeployment.value ? 'local files' : 'server/HPC files'} before starting the scan.`
    )
  }
  if (localHasLowFilenameConfidence.value) {
    hints.push(
      'The filename column could not be identified reliably. If this MSF is a CSV, try changing the header-row option and rerun preflight.'
    )
  }
  if ((localMsfPreflightResult.value?.summary?.duplicate_groups_detected || 0) > 0) {
    hints.push(
      'Duplicate filename rows inside the MSF can be merged directly in the Guided MSF Repair step.'
    )
  }
  if (!hints.length && localMsfPreflightResult.value) {
    hints.push('Proceed to Guided MSF Repair to inspect row-level issues and confirm the scan setup before processing starts.')
  }
  return hints
})
const recordResolutionSummary = computed(() => recordResolutionAnalysis.value?.summary || {})
const hasRecordResolutionPlan = computed(() => Boolean(preparedBatchSessionId.value && recordResolutionAnalysis.value))
const hasRecordResolutionBlockingConflicts = computed(() => {
  return Boolean(hasRecordResolutionPlan.value && recordResolutionSummary.value.can_continue === false)
})
const localContinueLabel = computed(() => {
  if (uploading.value) return 'Processing...'
  if (uploadMode.value === 'file') return 'Upload & Continue'
  if (storageStatus.value?.mode !== 'local') {
    if (recordResolutionLoading.value) return 'Analyzing record plan...'
    if (recordResolutionSaving.value) return 'Saving decisions...'
    if (hasRecordResolutionBlockingConflicts.value) return 'Resolve record plan to continue'
    if (hasRecordResolutionPlan.value) return 'Continue to MSF Analysis'
    return 'Scan & Continue'
  }
  if (recordResolutionLoading.value) return 'Analyzing record plan...'
  if (recordResolutionSaving.value) return 'Saving decisions...'
  if (hasRecordResolutionBlockingConflicts.value) return 'Resolve record plan to continue'
  if (hasRecordResolutionPlan.value) return 'Continue to MSF Analysis'
  if (!localMsfPreflightResult.value) return 'Run MSF Preflight First'
  return 'Prepare session & review record plan'
})

const uploadReadinessItems = computed(() => {
  if (uploadMode.value === 'file') {
    return [
      {
        label: 'Select submission files',
        ready: selectedFiles.value.length > 0,
        detail: selectedFiles.value.length > 0
          ? `${selectedFiles.value[0]?.name || 'One file'} is ready for upload.`
          : 'Choose one file to create the submission session.',
      },
    ]
  }

  if (storageStatus.value?.mode === 'local') {
    return [
      {
        label: 'Choose the session MSF',
        ready: !!selectedMsfPath.value,
        detail: selectedMsfPath.value
          ? selectedMsfPath.value
          : 'Select the Excel or CSV file that defines the batch metadata rows.',
      },
      {
        label: 'Confirm the target directory',
        ready: !!selectedMsfPath.value,
        detail: directoryPath.value
          ? `The scan will start from "${directoryPath.value}".`
          : `The scan will start from the root directory (${localInputRoot.value || '/data/local_input'}).`,
      },
      {
        label: 'Run MSF preflight',
        ready: !!localMsfPreflightResult.value,
        detail: localMsfPreflightResult.value
          ? (localMsfPreflightResult.value.is_valid
              ? 'Preflight completed. You can continue into the analysis step before the real scan starts.'
              : 'Preflight completed with blockers. You can still continue into guided MSF repair.')
          : 'Run preflight once so the application can explain the detected blockers and warnings.',
      },
      {
        label: 'Review the record-resolution plan',
        ready: hasRecordResolutionPlan.value && recordResolutionSummary.value.can_continue === true,
        detail: !hasRecordResolutionPlan.value
          ? `This runs after the ${batchPreparationLabel.value} is prepared.`
          : recordResolutionSummary.value.can_continue
            ? 'Every affected candidate has a saved action. Guided MSF analysis can continue.'
            : `${recordResolutionSummary.value.unresolved_count || 0} candidate(s) still need an explicit action before continuing.`,
      },
    ]
  }

  const validationReady = !!msfValidationResult.value
  const hasMatches = Number(msfValidationResult.value?.matched_count || 0) > 0 && !!msfValidationResult.value?.is_valid

  return [
    {
      label: 'Choose the ZIP with model files',
      ready: !!zipFile.value,
      detail: zipFile.value ? zipFile.value.name : 'Upload a ZIP containing the model assets for this batch.',
    },
    {
      label: 'Choose the MSF',
      ready: !!msfFile.value || !!selectedMsfPath.value,
      detail: msfFile.value?.name || selectedMsfPath.value || 'Upload the Excel or CSV file that describes the records.',
    },
    {
      label: 'Validate ZIP against MSF',
      ready: validationReady,
      detail: validationReady
        ? (msfValidationResult.value?.is_valid
            ? 'Validation completed successfully.'
            : 'Validation completed with errors. Review the results before continuing.')
        : 'Run validation once to confirm file-to-row matching before the batch workflow starts.',
    },
    {
      label: 'Confirm at least one asset match',
      ready: hasMatches,
      detail: hasMatches
        ? `${msfValidationResult.value?.matched_count || 0} file(s) matched the MSF.`
        : 'At least one valid file match is required to continue.',
    },
    {
      label: 'Review the record-resolution plan',
      ready: hasRecordResolutionPlan.value && recordResolutionSummary.value.can_continue === true,
      detail: !preparedBatchSessionId.value
        ? 'This runs after the ZIP or cloud batch session has been prepared.'
        : !hasRecordResolutionPlan.value
          ? 'Record-resolution analysis is loading for the prepared batch session.'
          : recordResolutionSummary.value.can_continue
            ? 'Every affected candidate has a saved action. Guided MSF analysis can continue.'
            : `${recordResolutionSummary.value.unresolved_count || 0} candidate(s) still need an explicit action before continuing.`,
    },
  ]
})

const uploadBlockingMessage = computed(() => {
  if (uploadMode.value === 'file') {
    return selectedFiles.value.length > 0 ? '' : 'Select at least one file to enable the primary action.'
  }

  if (storageStatus.value?.mode === 'local') {
    if (!selectedMsfPath.value) return 'Choose an MSF file first.'
    if (!localMsfPreflightResult.value) return 'Run MSF Preflight once so the next step can open with real diagnostics.'
    if (!hasRecordResolutionPlan.value) return `Prepare the ${batchPreparationLabel.value} so record resolution can be analyzed.`
    if (recordResolutionLoading.value) return 'Record-resolution analysis is still running.'
    if (recordResolutionSaving.value) return 'Save operations are still in progress.'
    if (hasRecordResolutionBlockingConflicts.value) return 'Resolve or skip every affected candidate before continuing into the batch workflow.'
    return ''
  }

  if (!zipFile.value) return 'Choose the ZIP with the model files.'
  if (!msfFile.value && !selectedMsfPath.value) return 'Choose the MSF file.'
  if (!msfValidationResult.value) return 'Run validation before continuing.'
  if (!msfValidationResult.value?.is_valid || Number(msfValidationResult.value?.matched_count || 0) <= 0) {
    return 'Resolve the validation problems or provide an MSF that matches at least one uploaded asset.'
  }
  if (!hasRecordResolutionPlan.value) {
    return preparedBatchSessionId.value
      ? 'Record-resolution analysis is still loading for the prepared batch session.'
      : ''
  }
  if (recordResolutionLoading.value) return 'Record-resolution analysis is still running.'
  if (recordResolutionSaving.value) return 'Save operations are still in progress.'
  if (hasRecordResolutionBlockingConflicts.value) return 'Resolve or skip every affected candidate before continuing into the batch workflow.'
  return ''
})

const uploadCtaHelp = computed(() => {
  if (uploadMode.value === 'file') {
    return 'This creates the session immediately and moves you to file review.'
  }
  if (storageStatus.value?.mode === 'local') {
    return hasRecordResolutionPlan.value
      ? 'This opens the guided MSF analysis step. The real directory scan starts there, not here.'
      : `This prepares the ${batchPreparationLabel.value} and opens the record-resolution review before guided MSF analysis continues.`
  }
  return hasRecordResolutionPlan.value
    ? 'This opens the guided MSF analysis step using the saved batch record plan.'
    : 'This creates the batch session, finishes ZIP or cloud processing, and then opens record-resolution review before guided MSF analysis.'
})

const selectedMsfIdentifier = computed(() => {
  if (storageStatus.value?.mode === 'local') {
    return selectedMsfPath.value || ''
  }
  return msfFile.value?.name || selectedMsfPath.value || ''
})

const isCsvMsfSelected = computed(() => {
  return selectedMsfIdentifier.value.toLowerCase().endsWith('.csv')
})

watch(isCsvMsfSelected, (isCsv) => {
  if (!isCsv) {
    useFirstRowAsHeader.value = true
    csvHeaderPreferenceTouched.value = false
  }
})

watch([useFirstRowAsHeader, csvHeaderPreferenceTouched], async () => {
  if (
    storageStatus.value?.mode === 'local' &&
    selectedMsfPath.value &&
    isCsvMsfSelected.value &&
    csvHeaderPreferenceTouched.value
  ) {
    await preflightLocalMsf()
  }
})

const buildMsfParseOptionsPayload = () => {
  const options = {}
  if (isCsvMsfSelected.value && csvHeaderPreferenceTouched.value) {
    options.use_first_row_as_header = useFirstRowAsHeader.value
  }
  return options
}

const appendMsfParseOptions = (formData) => {
  const options = buildMsfParseOptionsPayload()
  Object.entries(options).forEach(([key, value]) => {
    formData.append(key, String(value))
  })
  return options
}

const preflightLocalMsf = async () => {
  if (storageStatus.value?.mode !== 'local' || !selectedMsfPath.value) {
    return
  }

  localMsfPreflighting.value = true
  localMsfPreflightResult.value = null
  error.value = ''

  try {
    const parseOptions = buildMsfParseOptionsPayload()
    const response = await api.post(
      '/msf/patch',
      {
        msf_path: selectedMsfPath.value,
        directory_path: directoryPath.value || localInputRoot.value || undefined,
        duplicate_policy: 'merge_non_empty',
        apply: false,
        recursive: true,
        parse_options: parseOptions
      },
      { suppressGlobalError: true }
    )

    const payload = response.data || {}
    localMsfPreflightResult.value = payload
  } catch (err) {
    console.error('Local MSF preflight error:', err)
    error.value = err?.error?.message || err?.message || 'Failed to preflight local MSF.'
  } finally {
    localMsfPreflighting.value = false
  }
}

const canUpload = computed(() => {
  if (uploadMode.value === 'file') {
    return selectedFiles.value.length > 0
  } else {
    // For local mode, we need a selected MSF path
    if (storageStatus.value?.mode === 'local') {
      if (!selectedMsfPath.value || !localMsfPreflightResult.value) {
        return false
      }
      if (!preparedBatchSessionId.value) {
        return true
      }
      if (recordResolutionLoading.value || recordResolutionSaving.value) {
        return false
      }
      return Boolean(recordResolutionSummary.value.can_continue)
    }
    if (!preparedBatchSessionId.value) {
      return zipFile.value &&
        msfFile.value &&
        msfValidationResult.value?.is_valid &&
        msfValidationResult.value?.matched_count > 0
    }
    if (recordResolutionLoading.value || recordResolutionSaving.value) {
      return false
    }
    return Boolean(recordResolutionSummary.value.can_continue)
  }
})

const selectDirectFiles = (files) => {
  if (uploading.value) return
  if (files.length > 1) {
    error.value = 'Direct upload accepts one file. Choose a single file, or use a ZIP batch with an MSF for multiple files and separate textures.'
    return
  }
  if (!files.length) return
  if (files[0].size === 0) {
    error.value = 'This file is empty. Choose a file that contains a model or image.'
    return
  }
  selectedFiles.value = [files[0]]
  error.value = ''
  success.value = ''
}

const handleFileSelect = (event) => {
  selectDirectFiles(Array.from(event.target.files || []))
  event.target.value = ''
}

const handleDrop = (event) => {
  isDragging.value = false
  selectDirectFiles(Array.from(event.dataTransfer.files || []))
}

const removeFile = (index) => {
  if (!uploading.value) selectedFiles.value.splice(index, 1)
}

const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

// ZIP File Handlers
const handleZipFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) {
    setZipFile(file)
  }
}

const handleZipDrop = (event) => {
  if (uploading.value || validatingMsf.value) return
  if (event.dataTransfer.files.length > 1) {
    error.value = 'Choose one file for this field. No files were changed.'
    return
  }
  isZipDragging.value = false
  const file = event.dataTransfer.files[0]
  if (file) {
    setZipFile(file)
  }
}

const setZipFile = (file) => {
  if (uploading.value || validatingMsf.value) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    error.value = 'Invalid file type. Please select a ZIP file.'
    return
  }
  zipFile.value = file
  msfValidationResult.value = null
  zipMsfPreflightReport.value = null
  resetRecordResolutionAnalysis()
  error.value = ''
}

const removeZipFile = () => {
  zipFile.value = null
  zipPath.value = ''
  msfValidationResult.value = null
  zipMsfPreflightReport.value = null
  resetRecordResolutionAnalysis()
}

// MSF File Handlers
const handleMsfFileSelect = async (event) => {
  const file = event.target.files[0]
  if (file) {
    await setMsfFile(file)
  }
}

const handleMsfDrop = async (event) => {
  if (uploading.value || validatingMsf.value) return
  if (event.dataTransfer.files.length > 1) {
    error.value = 'Choose one file for this field. No files were changed.'
    return
  }
  isMsfDragging.value = false
  const file = event.dataTransfer.files[0]
  if (file) {
    await setMsfFile(file)
  }
}

const setMsfFile = async (file) => {
  if (uploading.value || validatingMsf.value) return
  const ext = file.name.split('.').pop().toLowerCase()
  if (!['xlsx', 'xls', 'csv'].includes(ext)) {
    error.value = 'Invalid file type. Please select an Excel (.xlsx) or CSV file.'
    return
  }

  msfFile.value = file
  msfValidationResult.value = null
  zipMsfPreflightReport.value = null
  resetRecordResolutionAnalysis()
  csvHeaderPreferenceTouched.value = false
  error.value = ''
}

const removeMsfFile = () => {
  msfFile.value = null
  msfPath.value = ''
  msfValidationResult.value = null
  zipMsfPreflightReport.value = null
  localMsfPreflightResult.value = null
  resetRecordResolutionAnalysis()
  csvHeaderPreferenceTouched.value = false
}

const applySuggestedLocalDirectory = async (relativePath) => {
  directoryPath.value = relativePath || ''
  await preflightLocalMsf()
}

const validateMsf = async () => {
  validatingMsf.value = true
  error.value = ''
  msfValidationResult.value = null
  zipMsfPreflightReport.value = null
  resetRecordResolutionAnalysis()

  try {
    const formData = new FormData()
    formData.append('zip_file', zipFile.value)
    formData.append('msf_file', msfFile.value)
    const parseOptions = appendMsfParseOptions(formData)

    const response = await api.post('/sessions/directory', formData, {
      params: { validate_only: true },
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    const payload = response.data || {}
    msfValidationResult.value = payload.msf_validation || payload
    zipMsfPreflightReport.value = payload.msf_preflight || null

    if (msfValidationResult.value?.is_valid) {
      const msfMapping = payload.msf_mapping || {}
      const fileMetadataMap = payload.file_metadata_map || {}
      const msfProfile = payload.msf_profile || {}
      workflowStore.setMsfData(
        msfFile.value.name,
        msfValidationResult.value,
        msfMapping,
        fileMetadataMap,
        msfProfile,
        msfProfile.parse_options || parseOptions
      )
    }

    if (!msfValidationResult.value.is_valid) {
      error.value = 'MSF validation failed. Please check the results below.'
    } else {
      success.value = 'MSF validated successfully against ZIP content.'
    }
  } catch (err) {
    console.error('MSF validation error:', err)
    error.value = err?.response?.data?.error?.message || err?.error?.message || err.message || 'Failed to validate MSF file.'
  } finally {
    validatingMsf.value = false
  }
}

const progressPercent = ref(null)
const uploadMonitorUnavailable = ref(false)
const visibleUploadPercent = computed(() => {
  if (uploadMode.value === 'file' || uploadStage.value === 2) return null
  return progressPercent.value
})
const uploadProgressLabel = computed(() => {
  if (uploadMode.value === 'file') return 'Uploading and checking your file…'
  if (uploadStage.value === 4) return 'Upload complete'
  if (uploadStage.value <= 1) return storageStatus.value?.mode === 'local' ? 'Starting directory scan…' : 'Transferring your files…'
  return 'Preparing files for review…'
})
const hasFailures = ref(false)
const uploadStatusMessage = ref('')

const continueAfterUpload = () => {
  if (workflowStore.isBatchMode) {
    workflowStore.goToStep(2)
    router.push('/workflow/msf-analysis')
    return
  }
  workflowStore.goToStep(3)
  router.push('/workflow/files')
}

const openPreparedBatchWorkflow = ({ selectedMsfPathValue = null, parseOptions = {}, validationPayload = null } = {}) => {
  if (!preparedBatchSessionId.value || !recordResolutionSummary.value.can_continue) {
    return false
  }

  const effectiveMsfIdentifier = selectedMsfPathValue || workflowStore.msfPath || selectedMsfPath.value || msfFile.value?.name || null
  workflowStore.setSessionId(preparedBatchSessionId.value)
  workflowStore.setBatchMode(true)

  if (storageStatus.value?.mode === 'local') {
    workflowStore.setMsfData(
      effectiveMsfIdentifier,
      validationPayload || localMsfPreflightResult.value,
      {},
      {},
      preparedBatchProfile.value || {},
      (preparedBatchProfile.value || {}).parse_options || parseOptions
    )
  }

  workflowStore.goToStep(2)
  uploadStage.value = 0
  uploading.value = false
  router.push('/workflow/msf-analysis')
  return true
}

const finalizeBatchRecordResolutionReview = async ({
  sessionId,
  selectedMsfPathValue = null,
  parseOptions = {},
  validationPayload = null,
  preparedProfile = null,
  autoContinueMessage,
  readyMessage,
  pendingMessage,
} = {}) => {
  if (!sessionId) {
    return null
  }

  const effectiveMsfIdentifier = selectedMsfPathValue || workflowStore.msfPath || selectedMsfPath.value || msfFile.value?.name || null
  preparedBatchSessionId.value = sessionId
  preparedBatchProfile.value = preparedProfile || preparedBatchProfile.value || workflowStore.msfProfile || {}
  workflowStore.setSessionId(sessionId)
  workflowStore.setBatchMode(true)

  if (storageStatus.value?.mode === 'local') {
    workflowStore.setMsfData(
      effectiveMsfIdentifier,
      validationPayload || localMsfPreflightResult.value,
      {},
      {},
      preparedBatchProfile.value || {},
      (preparedBatchProfile.value || {}).parse_options || parseOptions
    )
  }

  const analysis = await loadRecordResolutionAnalysis(sessionId, {})
  if (analysis?.summary?.can_continue && Number(analysis?.summary?.affected_count || 0) === 0) {
    success.value = autoContinueMessage
    openPreparedBatchWorkflow({
      selectedMsfPathValue: effectiveMsfIdentifier,
      parseOptions,
      validationPayload,
    })
    return analysis
  }

  success.value = analysis?.summary?.can_continue ? readyMessage : pendingMessage
  uploadStage.value = 0
  uploading.value = false
  return analysis
}

const pollProgress = async (sessionId, taskId = null) => {
    // 1. Poll Coordinator Task (if taskId provided)
    if (taskId) {
        let coordinatorDone = false
        while (!coordinatorDone) {
            try {
              const taskRes = await api.get(`/sessions/tasks/${taskId}`)
              const taskData = taskRes.data
              const status = taskData?.state

              if (status === 'SUCCESS' || status === 'coordinator_completed') {
                  // Check for logical failure returned as result
                  if (taskData.status === 'failed') {
                      throw new Error(taskData.error || 'Coordinator task failed')
                  }
                  coordinatorDone = true
              } else if (status === 'FAILURE') {
                  throw new Error(taskData.error || 'Coordinator failed (System Error)')
              }
              await new Promise(r => setTimeout(r, 1000))
            } catch (e) {
              throw e
            }
        }
    }

    // 2. Poll Real File Progress
    uploadStage.value = 3 // Processing files

    while (true) {
        try {
          const progressRes = await api.get(`/sessions/${sessionId}/progress`, { suppressGlobalError: true })
          const uploadProgress = progressRes.data?.upload_progress || {}
          const percent = uploadProgress.percent ?? progressRes.data?.percent ?? null
          const failed = uploadProgress.failed_count ?? progressRes.data?.failed ?? 0
          const currentStage = uploadProgress.current_stage || progressRes.data?.current_stage

          progressPercent.value = percent
          uploadMonitorUnavailable.value = false
          uploadStatusMessage.value = uploadProgress.status_message || 'Processing files...'

          if (currentStage === 'failed') {
              hasFailures.value = true
              error.value = uploadProgress.status_message || 'Upload processing failed.'
              break
          }

          if (percent >= 100) {
              if (failed > 0) {
                  hasFailures.value = true
                  error.value = `${failed} files failed to process.`
                  break
              } else {
                  uploadStage.value = 4 // Complete
                  break
              }
          }
        } catch (e) {
          uploadMonitorUnavailable.value = true
          console.warn("Progress poll failed", e)
        }
        await new Promise(r => setTimeout(r, 1000))
    }
}

const handleResume = async () => {
    if (!workflowStore.sessionId) return

    uploading.value = true
    error.value = ''
    hasFailures.value = false
    workflowStore.setBatchMode(true)

    try {
        await api.post(`/sessions/${workflowStore.sessionId}/resume`)
        // Resume polling (skip coordinator phase)
        await pollProgress(workflowStore.sessionId, null)

        if (!hasFailures.value) {
            clearDirectoryUploadState()
            await finalizeBatchRecordResolutionReview({
              sessionId: workflowStore.sessionId,
              autoContinueMessage: 'Resume complete. No affected record candidates were found.',
              readyMessage: 'Resume complete. Review the saved record-resolution plan before continuing.',
              pendingMessage: 'Resume complete. Review the affected record candidates below and save the plan before continuing.',
            })
        }
    } catch (e) {
        error.value = "Failed to resume: " + (e.message || e)
        hasFailures.value = true // Re-enable resume button
    } finally {
    if (!hasFailures.value) uploading.value = false
    }
}

const resumeSavedDirectoryUpload = async () => {
  const saved = readDirectoryUploadState()
  if (!saved?.submit_token) return

  try {
    const recovered = await recoverDirectorySubmission(saved.submit_token)
    if (!recovered?.session_id) {
      clearDirectoryUploadState()
      return
    }

    persistDirectorySubmitContext({
      submitToken: recovered.submit_token || saved.submit_token,
      sessionId: recovered.session_id,
      taskId: recovered.task_id || null
    })

    if (recovered.session_status === 'completed') {
      clearDirectoryUploadState()
      return
    }

    if (recovered.session_status === 'failed') {
      clearDirectoryUploadState()
      return
    }

    uploadMode.value = 'directory'
    uploading.value = true
    error.value = ''
    success.value = 'Recovered in-flight upload. Resuming progress polling.'
    uploadStage.value = recovered.task_id ? 2 : 3
    workflowStore.setSessionId(recovered.session_id)
    workflowStore.setBatchMode(true)
    await pollProgress(recovered.session_id, recovered.task_id || null)

    if (!hasFailures.value) {
      clearDirectoryUploadState()
      await finalizeBatchRecordResolutionReview({
        sessionId: recovered.session_id,
        autoContinueMessage: 'Recovered upload completed successfully with no affected record candidates.',
        readyMessage: 'Recovered upload completed successfully. Review the saved record-resolution plan before continuing.',
        pendingMessage: 'Recovered upload completed successfully. Review the affected record candidates below and save the plan before continuing.',
      })
    }
  } catch (recoverErr) {
    console.warn('Pending directory upload recovery failed:', recoverErr)
  } finally {
    if (!hasFailures.value) {
      uploading.value = false
    }
  }
}

const loadHpcStatus = async () => {
  try {
    const response = await hpcLinkService.getStatus({ purpose: 'workflow' })
    hpcStatus.value = response.data || null
  } catch (err) {
    console.warn('Failed to load HPC-Link status:', err)
    hpcStatus.value = { enabled: false, can_allocate: false }
  }
}

const refreshHpcAllocation = async () => {
  const allocationId = hpcAllocation.value?.allocation_id
  if (!allocationId) return
  try {
    const response = await hpcLinkService.getAllocation(allocationId)
    hpcAllocation.value = response.data?.allocation || hpcAllocation.value
  } catch (err) {
    console.warn('Failed to refresh HPC-Link allocation:', err)
  }
}

const requestHpcResources = async () => {
  hpcAllocationError.value = ''

  hpcAllocationLoading.value = true
  try {
    const payload = { purpose: 'workflow' }
    if (workflowStore.sessionId) {
      payload.session_id = workflowStore.sessionId
    }
    const response = await hpcLinkService.requestAllocation(payload)
    hpcAllocation.value = response.data?.allocation || null
    await refreshHpcAllocation()
    if (hpcAllocation.value?.status === 'running') {
      toast.success('HPC-Link allocation is active.')
    } else {
      toast.info('HPC-Link allocation request is queued.')
    }
  } catch (err) {
    hpcAllocationError.value = err?.error?.message || err?.message || 'HPC-Link allocation request failed.'
  } finally {
    hpcAllocationLoading.value = false
  }
}

const waitForHpcAllocationReady = async ({ maxAttempts = 60, delayMs = 5000 } = {}) => {
  if (!hpcAllocation.value?.allocation_id) return null
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await refreshHpcAllocation()
    if (hpcAllocation.value?.status === 'running') {
      return hpcAllocation.value
    }
    if (['failed', 'released', 'expired', 'cancelled'].includes(hpcAllocation.value?.status)) {
      throw new Error(hpcAllocation.value?.last_error || `HPC-Link allocation ended with status ${hpcAllocation.value?.status}.`)
    }
    uploadStatusMessage.value = `Waiting for HPC-Link allocation (${hpcAllocation.value?.status || 'queued'})...`
    await new Promise(resolve => window.setTimeout(resolve, delayMs))
  }
  throw new Error('HPC-Link allocation did not become ready in time.')
}

onMounted(async () => {
  await Promise.all([
    loadHpcStatus(),
    resumeSavedDirectoryUpload()
  ])
})

const handleUpload = async () => {
  if (uploading.value || !canUpload.value) return
  uploadMonitorUnavailable.value = false
  uploading.value = true
  error.value = ''
  success.value = ''
  uploadStage.value = 0
  progressPercent.value = null
  uploadStatusMessage.value = ''
  hasFailures.value = false

  const selectedMsfPathValue = msfFile.value?.name || selectedMsfPath.value || null
  const parseOptions = buildMsfParseOptionsPayload()
  const existingValidation = msfValidationResult.value || null
  const existingMapping = existingValidation ? (workflowStore.msfMapping || {}) : {}
  const existingFileMetadataMap = existingValidation ? (workflowStore.fileMetadataMap || {}) : {}
  const existingProfile = existingValidation ? (workflowStore.msfProfile || {}) : {}
  let directorySubmitToken = null
  workflowStore.resetWorkflow()

  // Set Batch Mode if MSF is selected/provided
  if (uploadMode.value === 'directory' && selectedMsfPathValue) {
    workflowStore.setMsfData(
      selectedMsfPathValue,
      existingValidation,
      existingMapping,
      existingFileMetadataMap,
      existingProfile,
      parseOptions
    )
  }

  try {
    if (uploadMode.value === 'file') {
      const file = selectedFiles.value[0]
      const response = await fileService.uploadFile(file, buildWorkspacePayload())
      workflowStore.setSessionId(response.data.session_id)
      workflowStore.setUploadedFiles(response.data.foundFiles || [])
      success.value = 'Files uploaded successfully!'

      continueAfterUpload()

    } else {
       // Directory/ZIP Mode
       if (storageStatus.value?.mode === 'local') {
          if (preparedBatchSessionId.value && recordResolutionAnalysis.value && recordResolutionSummary.value.can_continue) {
            success.value = 'Record-resolution review is complete. Opening Guided MSF Repair.'
            openPreparedBatchWorkflow({
              selectedMsfPathValue,
              parseOptions,
              validationPayload: localMsfPreflightResult.value,
            })
            return
          }

          if (!localMsfPreflightResult.value) {
             await preflightLocalMsf()
          }
          if (!localMsfPreflightResult.value) {
            throw new Error('MSF preflight could not be completed.')
          }

          uploadStage.value = 1
          const prepareResponse = await msfService.prepareLocalWorkflowSession({
            msf_path: selectedMsfPath.value,
            directory_path: directoryPath.value || localInputRoot.value || undefined,
            duplicate_policy: 'merge_non_empty',
            recursive: true,
            parse_options: parseOptions,
            ...buildWorkspacePayload(),
          })
          const payload = prepareResponse.data || {}
          const preparedProfile = payload.msf_profile || payload.analysis?.msf_profile || {}
          const analysis = await finalizeBatchRecordResolutionReview({
            sessionId: payload.session_id,
            selectedMsfPathValue,
            parseOptions,
            validationPayload: localMsfPreflightResult.value,
            preparedProfile,
            autoContinueMessage: localMsfPreflightResult.value.is_valid
              ? 'Record-resolution analysis found no affected candidates. Opening Guided MSF Repair.'
              : 'MSF issues were found. Opening Guided MSF Repair so they can be fixed in the application.',
            readyMessage: 'Record-resolution review is already complete. Continue when you are ready.',
            pendingMessage: 'Record-resolution analysis is ready. Review the affected candidates below and save the plan before continuing.',
          })
          if (analysis?.summary?.can_continue && Number(analysis?.summary?.affected_count || 0) === 0) {
            return
          }
          return
       }

       if (preparedBatchSessionId.value && recordResolutionAnalysis.value && recordResolutionSummary.value.can_continue) {
          success.value = 'Record-resolution review is complete. Opening Guided MSF Repair.'
          openPreparedBatchWorkflow({
            selectedMsfPathValue,
            parseOptions,
            validationPayload: existingValidation,
          })
          return
       }

       const formData = new FormData()
       const submitState = ensureDirectorySubmitState()
       directorySubmitToken = submitState.submit_token
       formData.append('submit_token', directorySubmitToken)
       Object.entries(buildWorkspacePayload()).forEach(([key, value]) => {
         if (value === undefined || value === null || value === '') return
         formData.append(key, String(value))
       })

       const activeHpcAllocation = storageStatus.value?.mode === 'pure_cloud' && hpcAllocation.value?.allocation_id
         ? await waitForHpcAllocationReady()
         : null
       if (activeHpcAllocation?.allocation_id) {
         uploadStatusMessage.value = 'Uploading ZIP to cloud storage and staging it on the HPC...'
         progressPercent.value = null
         const streamResponse = await api.uploadFileStream(
           zipFile.value,
           (percent) => { progressPercent.value = percent },
           {
             hpcAllocationId: activeHpcAllocation.allocation_id,
             hpcRelativeDir: 'uploads'
           }
         )
         const cloudUpload = streamResponse.data || {}
         const cloudPath = cloudUpload.remote_path || cloudUpload.file_id
         if (!cloudPath || !cloudUpload.storage_type) {
           throw new Error('Cloud upload completed but did not return a usable cloud reference.')
         }
         formData.append('cloud_path', cloudPath)
         formData.append('cloud_storage_type', cloudUpload.storage_type)
         formData.append('cloud_original_filename', zipFile.value.name)
         formData.append('hpc_allocation_id', activeHpcAllocation.allocation_id)
         hpcAllocation.value = cloudUpload.hpc_staging?.allocation || hpcAllocation.value
       } else {
         formData.append('zip_file', zipFile.value)
       }

       if (msfFile.value) {
          formData.append('msf_file', msfFile.value)
       } else if (selectedMsfPath.value) {
          formData.append('msf_path', selectedMsfPath.value)
       }

       if (directoryPath.value) {
          formData.append('directory_path', directoryPath.value)
       }
       appendMsfParseOptions(formData)

       // Step 1: Upload / Init
       uploadStage.value = 1

       const response = await api.post('/sessions/directory', formData, {
         headers: { 'Content-Type': 'multipart/form-data' },
         onUploadProgress: (progressEvent) => {
            if (progressEvent.total && storageStatus.value?.mode !== 'local') {
               // Only show upload progress if we are actually uploading a ZIP
               // Local mode is instant init
               const p = Math.round((progressEvent.loaded * 100) / progressEvent.total)
               progressPercent.value = p < 100 ? p : null
            }
         }
       })

       const { task_id, session_id, submit_token } = response.data
       directorySubmitToken = submit_token || directorySubmitToken
       persistDirectorySubmitContext({
         submitToken: directorySubmitToken,
         sessionId: session_id,
         taskId: task_id || null
       })
       workflowStore.setSessionId(session_id)

       // Step 2 & 3: Poll Progress
       progressPercent.value = null
       uploadStage.value = 2 // Coordinator running
       await pollProgress(session_id, task_id)

       // Step 4: Finalize
       if (hasFailures.value) {
          // Stay on page to allow resume or review
          uploading.value = false
          return
       }

       clearDirectoryUploadState()
       const analysis = await finalizeBatchRecordResolutionReview({
         sessionId: session_id,
         selectedMsfPathValue,
         parseOptions,
         validationPayload: existingValidation,
         preparedProfile: existingProfile,
         autoContinueMessage: 'Processing complete. No affected record candidates were found.',
         readyMessage: 'Processing complete. Review the saved record-resolution plan before continuing.',
         pendingMessage: 'Record-resolution analysis is ready. Review the affected candidates below and save the plan before continuing.',
       })
       if (analysis?.summary?.can_continue && Number(analysis?.summary?.affected_count || 0) === 0) {
         return
       }
    }

  } catch (err) {
    console.error('Upload error:', err)
    let errorMessage = 'Operation failed.'
    const backendError = err?.response?.data?.error || err?.error || null
    const isValidationFailure = backendError?.code === 'VALIDATION_ERROR'

    if (uploadMode.value === 'directory' && directorySubmitToken && !isValidationFailure) {
      try {
        const recovered = await recoverDirectorySubmission(directorySubmitToken)
        if (recovered?.session_id) {
          persistDirectorySubmitContext({
            submitToken: recovered.submit_token || directorySubmitToken,
            sessionId: recovered.session_id,
            taskId: recovered.task_id || null
          })
          workflowStore.setSessionId(recovered.session_id)
          workflowStore.setBatchMode(true)
          uploadStage.value = recovered.task_id ? 2 : 3
          await pollProgress(recovered.session_id, recovered.task_id || null)
          if (!hasFailures.value) {
            clearDirectoryUploadState()
            await finalizeBatchRecordResolutionReview({
              sessionId: recovered.session_id,
              selectedMsfPathValue,
              parseOptions,
              validationPayload: existingValidation,
              preparedProfile: existingProfile,
              autoContinueMessage: 'Recovered in-flight upload completed with no affected record candidates.',
              readyMessage: 'Recovered in-flight upload completed. Review the saved record-resolution plan before continuing.',
              pendingMessage: 'Recovered in-flight upload completed. Review the affected record candidates below and save the plan before continuing.',
            })
            return
          }
        }
      } catch (recoverErr) {
        console.warn('Upload recovery failed:', recoverErr)
      }
    }

    if (err.response?.data?.error) { // Axios error with response
        errorMessage = typeof err.response.data.error === 'string'
            ? err.response.data.error
            : (err.response.data.error.message || JSON.stringify(err.response.data.error))
    } else if (backendError) {
        errorMessage = backendError.message || JSON.stringify(backendError)
    } else if (err.message) {
        errorMessage = err.message
    }

    error.value = errorMessage
    uploadStage.value = 0
  } finally {
    if (!hasFailures.value) {
        uploading.value = false
    }
  }
}
</script>
