<template>
  <div class="min-h-screen bg-gray-50">
    <div class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <section class="bg-white shadow-sm rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-6 py-5 border-b border-gray-200 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-gray-900">Account Configuration</h1>
            <p class="text-sm text-gray-500 mt-1">Manage your identity, personal Zenodo credentials, and default workspace.</p>
          </div>
          <div class="flex items-center gap-3">
            <div class="h-11 w-11 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-sm font-semibold">
              {{ userInitials }}
            </div>
            <div>
              <p class="text-sm font-medium text-gray-900">{{ authStore.user?.email }}</p>
              <p class="text-xs text-gray-500 capitalize">{{ authStore.user?.role }} account</p>
            </div>
          </div>
        </div>
        <div class="px-6 py-4 grid grid-cols-1 sm:grid-cols-4 gap-4 bg-gray-50">
          <div class="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-gray-500">Account ID</p>
            <p class="text-sm font-medium text-gray-900 mt-1">#{{ authStore.user?.id }}</p>
          </div>
          <div class="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-gray-500">Role</p>
            <p class="text-sm font-medium text-gray-900 mt-1 capitalize">{{ authStore.user?.role }}</p>
          </div>
          <div class="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-gray-500">Member Since</p>
            <p class="text-sm font-medium text-gray-900 mt-1">{{ memberSince }}</p>
          </div>
          <div class="rounded-lg border border-gray-200 bg-white px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-gray-500">Institutions</p>
            <p class="text-sm font-medium text-gray-900 mt-1">{{ authStore.institutions.length }}</p>
          </div>
        </div>
      </section>

      <section
        v-if="passwordChangeRequired"
        data-testid="password-change-required-banner"
        class="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900"
      >
        <p class="font-semibold">Password change required</p>
        <p class="mt-1">An administrator reset your recovery access. Update your password before continuing.</p>
      </section>

      <section class="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <article class="xl:col-span-2 bg-white shadow-sm rounded-xl border border-gray-200">
          <div class="px-6 py-5 border-b border-gray-200">
            <h2 class="text-lg font-semibold text-gray-900">Profile</h2>
            <p class="text-sm text-gray-500 mt-1">These fields are returned with your account context and can be used as defaults across institution workspaces.</p>
          </div>
          <form class="p-6 grid grid-cols-1 md:grid-cols-2 gap-4" @submit.prevent="handleProfileUpdate">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input v-model.trim="profileForm.email" type="email" required class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Display name</label>
              <input v-model.trim="profileForm.display_name" type="text" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Profile slug</label>
              <input v-model.trim="profileForm.slug" type="text" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Full name</label>
              <input v-model.trim="profileForm.full_name" type="text" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div class="relative">
              <label class="block text-sm font-medium text-gray-700 mb-1">Institutional affiliation</label>
              <div class="flex gap-2">
                <input
                  v-model.trim="institutionQuery"
                  data-testid="institution-affiliation-input"
                  type="text"
                  autocomplete="off"
                  class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                  @input="scheduleInstitutionSuggestions"
                  @focus="openInstitutionSuggestions"
                  @keydown.escape="institutionDropdownOpen = false"
                />
                <button
                  type="button"
                  data-testid="institution-create-button"
                  :disabled="affiliationSaving || !institutionQuery"
                  class="shrink-0 rounded-md border border-indigo-200 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
                  @click="createAffiliation(false)"
                >
                  Set
                </button>
              </div>
              <div
                v-if="institutionDropdownOpen && institutionSuggestions.length"
                data-testid="institution-suggestions"
                class="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-gray-200 bg-white shadow-lg"
              >
                <button
                  v-for="institution in institutionSuggestions"
                  :key="institution.id"
                  type="button"
                  class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-indigo-50"
                  @mousedown.prevent="selectInstitution(institution)"
                >
                  <span class="font-medium text-gray-900">{{ institution.name }}</span>
                  <span class="text-xs text-gray-500">{{ Math.round((institution.similarity || 0) * 100) }}%</span>
                </button>
              </div>
              <div v-if="similarInstitutions.length" data-testid="similar-institution-warning" class="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p class="font-medium">A similar institution already exists.</p>
                <div class="mt-2 flex flex-wrap gap-2">
                  <button
                    v-for="institution in similarInstitutions"
                    :key="`similar-${institution.id}`"
                    type="button"
                    class="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-amber-900 ring-1 ring-amber-200 hover:bg-amber-100"
                    @click="selectInstitution(institution)"
                  >
                    Use {{ institution.name }}
                  </button>
                  <button
                    type="button"
                    class="rounded-md bg-amber-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-800"
                    @click="createAffiliation(true)"
                  >
                    Create anyway
                  </button>
                </div>
              </div>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">ORCID</label>
              <input v-model.trim="profileForm.orcid" type="text" placeholder="0000-0000-0000-0000" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Profile visibility</label>
              <select v-model="profileForm.profile_visibility" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                <option value="private">Private</option>
                <option value="internal">Internal</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Website URL</label>
              <input v-model.trim="profileForm.website_url" type="url" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Avatar URL</label>
              <input v-model.trim="profileForm.avatar_url" type="url" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Default institution</label>
              <select v-model="profileForm.default_institution_id" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                <option :value="null">No default institution</option>
                <option v-for="institution in authStore.institutions" :key="institution.id" :value="institution.id">
                  {{ institution.name }}
                </option>
              </select>
            </div>
            <div class="md:col-span-2">
              <label class="block text-sm font-medium text-gray-700 mb-1">Bio</label>
              <textarea v-model.trim="profileForm.bio" rows="3" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"></textarea>
            </div>
            <div class="md:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label class="inline-flex items-center gap-2 text-sm text-gray-700">
                <input v-model="profileForm.show_email" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                Show email
              </label>
              <label class="inline-flex items-center gap-2 text-sm text-gray-700">
                <input v-model="profileForm.show_orcid" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                Show ORCID
              </label>
              <label class="inline-flex items-center gap-2 text-sm text-gray-700">
                <input v-model="profileForm.show_affiliation" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                Show affiliation
              </label>
            </div>
            <div class="md:col-span-2 flex justify-end">
              <button
                type="submit"
                :disabled="profileSaving || !profileChanged"
                class="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ profileSaving ? 'Saving...' : 'Save profile' }}
              </button>
            </div>
          </form>
        </article>

        <article class="bg-white shadow-sm rounded-xl border border-gray-200">
          <div class="px-6 py-5 border-b border-gray-200">
            <h2 class="text-lg font-semibold text-gray-900">Institutions</h2>
            <p class="text-sm text-gray-500 mt-1">Your memberships determine which shared workspaces you can access.</p>
          </div>
          <div class="p-6 space-y-4">
            <div v-if="!authStore.institutions.length" class="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
              No institution memberships yet.
            </div>
            <div
              v-for="institution in authStore.institutions"
              :key="institution.id"
              class="rounded-lg border border-gray-200 p-4"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-gray-900">{{ institution.name }}</p>
                  <p class="text-xs text-gray-500 mt-1 capitalize">{{ institution.role }} workspace role</p>
                </div>
                <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                  {{ institution.slug }}
                </span>
              </div>
            </div>
            <router-link
              v-if="authStore.institutions.length || authStore.user?.role === 'admin'"
              to="/account/institutions"
              class="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium text-indigo-600 border border-indigo-200 hover:bg-indigo-50"
            >
              Open institution settings
            </router-link>
          </div>
        </article>
      </section>

      <section class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <article class="bg-white shadow-sm rounded-xl border border-gray-200">
          <div class="px-6 py-5 border-b border-gray-200">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-semibold text-gray-900">Zenodo Keys</h2>
              <router-link
                to="/docs/zenodo-api-keys"
                class="inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-400 hover:bg-indigo-50 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                aria-label="Open Zenodo API key documentation"
                title="Open Zenodo API key documentation"
              >
                <InformationCircleIcon class="h-4 w-4" aria-hidden="true" />
              </router-link>
            </div>
            <p class="text-sm text-gray-500 mt-1">Manage named keys, accepted shares, and the active Sandbox and Production keys used by uploads.</p>
          </div>
          <div class="p-6 space-y-4">
            <form class="rounded-xl border border-gray-200 p-4 space-y-3" @submit.prevent="createCredential">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="block text-sm font-medium text-gray-700 mb-1">Key name</label>
                  <input v-model.trim="newCredential.name" type="text" required placeholder="Team Sandbox key" data-testid="zenodo-key-name" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
                </div>
                <div>
                  <div class="mb-1 flex items-center gap-1.5">
                    <label class="block text-sm font-medium text-gray-700">Environment</label>
                    <router-link
                      to="/docs/zenodo-api-keys"
                      class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      aria-label="Open documentation for Zenodo key environments"
                      title="Open documentation for Zenodo key environments"
                    >
                      <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                    </router-link>
                  </div>
                  <select v-model="newCredential.environment" data-testid="zenodo-key-environment" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
                    <option value="sandbox">Sandbox</option>
                    <option value="production">Production</option>
                  </select>
                </div>
              </div>
              <div>
                <div class="mb-1 flex items-center gap-1.5">
                  <label class="block text-sm font-medium text-gray-700">API key</label>
                  <router-link
                    to="/docs/security-and-credentials"
                    class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Open documentation for secure Zenodo API key storage"
                    title="Open documentation for secure Zenodo API key storage"
                  >
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </router-link>
                </div>
                <input v-model.trim="newCredential.token" type="password" required placeholder="Enter Zenodo API key" data-testid="zenodo-key-token" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
              </div>
              <div class="flex justify-end">
                <button type="submit" data-testid="zenodo-key-add" :disabled="credentialLoading || !newCredential.token || !newCredential.name" class="px-3 py-2 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50">
                  {{ credentialLoading ? 'Saving...' : 'Add key' }}
                </button>
              </div>
            </form>

            <div v-if="incomingShares.length" class="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
              <p class="text-sm font-semibold text-amber-900">Pending shared keys</p>
              <div v-for="share in incomingShares" :key="share.id" class="rounded-lg border border-amber-200 bg-white p-3">
                <p class="text-sm font-medium text-gray-900">{{ share.credential?.name }}</p>
                <p class="text-xs text-gray-500 mt-1">
                  {{ formatEnvironment(share.credential?.environment) }} shared by {{ share.shared_by?.email }}
                </p>
                <div class="mt-3 flex flex-wrap gap-2">
                  <button type="button" class="px-3 py-1.5 text-xs font-medium text-white bg-emerald-600 rounded-md hover:bg-emerald-700" @click="acceptShare(share.id)">Accept</button>
                  <button type="button" class="px-3 py-1.5 text-xs font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50" @click="declineShare(share.id)">Decline</button>
                </div>
              </div>
            </div>

            <div v-for="environment in credentialEnvironments" :key="environment" class="space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-gray-900">{{ formatEnvironment(environment) }}</p>
                  <p class="text-xs text-gray-500">
                    Active key: {{ activeCredential(environment)?.name || 'Not configured' }}
                    <router-link
                      to="/docs/zenodo-api-keys"
                      class="ml-1 inline-flex align-middle text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      aria-label="Open documentation for active Zenodo keys"
                      title="Open documentation for active Zenodo keys"
                    >
                      <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                    </router-link>
                  </p>
                </div>
                <span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="environment === 'sandbox' ? 'bg-indigo-100 text-indigo-700' : 'bg-emerald-100 text-emerald-700'">
                  {{ formatEnvironment(environment) }}
                </span>
              </div>

              <div v-if="!credentialsByEnvironment(environment).length" class="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
                No {{ environment }} keys available.
              </div>

              <div v-for="credential in credentialsByEnvironment(environment)" :key="credential.id" class="rounded-xl border border-gray-200 p-4 space-y-3" :data-testid="`zenodo-credential-${credential.id}`">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div class="flex flex-wrap items-center gap-2">
                      <p class="text-sm font-semibold text-gray-900">{{ credential.name }}</p>
                      <span v-if="credential.active" class="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Active</span>
                      <span class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-gray-600">{{ credential.source === 'shared' ? 'Shared' : 'Mine' }}</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-1">Token: <span class="font-medium text-gray-700">{{ credential.masked_preview || 'Hidden' }}</span></p>
                    <p class="text-xs text-gray-500 mt-1">Validation: <span class="font-medium text-gray-700 capitalize">{{ credential.validation_status || 'unknown' }}</span></p>
                    <p v-if="credential.source === 'shared'" class="text-xs text-gray-500 mt-1">Shared by {{ credential.shared_by?.email || credential.owner?.email }}</p>
                  </div>
                  <button type="button" :disabled="credential.active || credentialLoading" :data-testid="`zenodo-credential-set-active-${credential.id}`" class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50" @click="setActiveCredential(credential)">
                    {{ credential.active ? 'Active key' : 'Set active' }}
                  </button>
                </div>

                <div class="flex flex-wrap gap-2">
                  <button type="button" :disabled="credentialLoading" :data-testid="`zenodo-credential-validate-${credential.id}`" class="px-3 py-2 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50" @click="validateCredentialById(credential.id)">Validate</button>
                  <template v-if="credential.source !== 'shared'">
                    <div class="flex min-w-[14rem] flex-1 items-center gap-2">
                      <input v-model.trim="shareEmails[credential.id]" type="email" placeholder="Recipient email" class="min-w-0 flex-1 rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
                      <router-link
                        to="/docs/security-and-credentials"
                        class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-gray-400 hover:bg-indigo-50 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        aria-label="Open documentation for secure Zenodo key sharing"
                        title="Open documentation for secure Zenodo key sharing"
                      >
                        <InformationCircleIcon class="h-4 w-4" aria-hidden="true" />
                      </router-link>
                    </div>
                    <button type="button" :disabled="credentialLoading || !shareEmails[credential.id]" class="px-3 py-2 text-xs font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50" @click="shareCredential(credential)">Share</button>
                    <button type="button" :disabled="credentialLoading" class="px-3 py-2 text-xs font-medium text-red-600 border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50" @click="deleteCredentialById(credential.id)">Delete</button>
                  </template>
                </div>

                <ZenodoCredentialValidationReport :credential="credential" />
              </div>
            </div>
          </div>
        </article>

        <article class="bg-white shadow-sm rounded-xl border border-gray-200">
          <div class="px-6 py-5 border-b border-gray-200">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-semibold text-gray-900">Security</h2>
              <router-link
                to="/docs/security-and-credentials"
                class="inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-400 hover:bg-indigo-50 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                aria-label="Open security and credentials documentation"
                title="Open security and credentials documentation"
              >
                <InformationCircleIcon class="h-4 w-4" aria-hidden="true" />
              </router-link>
            </div>
            <p class="text-sm text-gray-500 mt-1">Change your password regularly to keep your account secure.</p>
          </div>
          <form class="p-6 space-y-4 border-b border-gray-200" @submit.prevent="handlePasswordUpdate">
            <div>
              <div class="mb-1 flex items-center gap-1.5">
                <label class="block text-sm font-medium text-gray-700">Current password</label>
                <router-link
                  to="/docs/security-and-credentials"
                  class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  aria-label="Open password security documentation"
                  title="Open password security documentation"
                >
                  <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                </router-link>
              </div>
              <input v-model="passwordForm.currentPassword" type="password" required class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <div class="mb-1 flex items-center gap-1.5">
                <label class="block text-sm font-medium text-gray-700">New password</label>
                <router-link
                  to="/docs/security-and-credentials"
                  class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  aria-label="Open password security documentation"
                  title="Open password security documentation"
                >
                  <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                </router-link>
              </div>
              <input v-model="passwordForm.newPassword" type="password" required minlength="8" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div>
              <div class="mb-1 flex items-center gap-1.5">
                <label class="block text-sm font-medium text-gray-700">Confirm new password</label>
                <router-link
                  to="/docs/security-and-credentials"
                  class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  aria-label="Open password security documentation"
                  title="Open password security documentation"
                >
                  <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                </router-link>
              </div>
              <input v-model="passwordForm.confirmNewPassword" type="password" required minlength="8" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
            </div>
            <div class="flex justify-end">
              <button
                type="submit"
                :disabled="passwordSaving"
                class="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium text-white bg-gray-900 hover:bg-gray-800 disabled:opacity-50"
              >
                {{ passwordSaving ? 'Updating...' : 'Update password' }}
              </button>
            </div>
          </form>
          <div class="p-6 space-y-4">
            <div>
              <div class="flex items-center gap-1.5">
                <h3 class="text-sm font-semibold text-gray-900">Recovery codes</h3>
                <router-link
                  to="/docs/security-and-credentials"
                  class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  aria-label="Open recovery code documentation"
                  title="Open recovery code documentation"
                >
                  <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                </router-link>
              </div>
              <p class="text-sm text-gray-500 mt-1">
                Recovery codes can be used instead of an email MFA code after you enter your password.
              </p>
            </div>
            <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700">
              <span class="font-medium">{{ recoveryCodeStatus.remaining_count ?? 0 }}</span>
              recovery code{{ recoveryCodeStatus.remaining_count === 1 ? '' : 's' }} available.
              <span v-if="recoveryCodeStatus.used_count"> {{ recoveryCodeStatus.used_count }} used.</span>
            </div>
            <form data-testid="recovery-code-form" class="space-y-3" @submit.prevent="handleRecoveryCodeRegeneration">
              <div>
                <div class="mb-1 flex items-center gap-1.5">
                  <label class="block text-sm font-medium text-gray-700">Current password</label>
                  <router-link
                    to="/docs/security-and-credentials"
                    class="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    aria-label="Open recovery code security documentation"
                    title="Open recovery code security documentation"
                  >
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </router-link>
                </div>
                <input
                  v-model="recoveryCodePassword"
                  data-testid="recovery-code-password"
                  type="password"
                  required
                  class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </div>
              <button
                type="submit"
                data-testid="regenerate-recovery-codes"
                :disabled="recoveryCodeLoading || !recoveryCodePassword"
                class="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
              >
                {{ recoveryCodeLoading ? 'Generating...' : 'Generate new recovery codes' }}
              </button>
            </form>
            <div v-if="generatedRecoveryCodes.length" data-testid="generated-recovery-codes" class="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <p class="text-sm font-semibold text-amber-900">Save these codes now. They will not be shown again.</p>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  data-testid="copy-recovery-codes"
                  class="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
                  @click="copyRecoveryCodes"
                >
                  Copy all
                </button>
                <button
                  type="button"
                  data-testid="download-recovery-codes"
                  class="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
                  @click="downloadRecoveryCodes"
                >
                  Download .txt
                </button>
              </div>
              <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-sm text-gray-900">
                <div v-for="item in generatedRecoveryCodes" :key="item" class="rounded bg-white px-3 py-2 border border-amber-100">
                  {{ item }}
                </div>
              </div>
              <label class="mt-4 flex items-center gap-2 text-sm text-amber-950">
                <input
                  v-model="recoveryCodesSaved"
                  data-testid="recovery-codes-saved"
                  type="checkbox"
                  class="rounded border-amber-300 text-amber-700 focus:ring-amber-500"
                />
                I have saved these recovery codes
              </label>
              <button
                type="button"
                data-testid="clear-generated-recovery-codes"
                :disabled="!recoveryCodesSaved"
                class="mt-3 rounded-md bg-amber-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-900 disabled:opacity-50"
                @click="clearGeneratedRecoveryCodes"
              >
                Hide saved codes
              </button>
            </div>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { InformationCircleIcon } from '@heroicons/vue/24/outline'
import ZenodoCredentialValidationReport from '@/components/account/ZenodoCredentialValidationReport.vue'
import authService from '@/services/auth.service'
import institutionService from '@/services/institution.service'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const authStore = useAuthStore()
const route = useRoute()
const toast = useToast()

const credentialEnvironments = ['sandbox', 'production']

const buildProfileForm = (user) => ({
  email: user?.email || '',
  slug: user?.slug || '',
  display_name: user?.display_name || '',
  full_name: user?.full_name || '',
  affiliation: user?.affiliation || '',
  orcid: user?.orcid || '',
  bio: user?.bio || '',
  website_url: user?.website_url || '',
  avatar_url: user?.avatar_url || '',
  profile_visibility: user?.profile_visibility || 'private',
  show_email: Boolean(user?.show_email),
  show_orcid: Boolean(user?.show_orcid),
  show_affiliation: Boolean(user?.show_affiliation),
  default_institution_id: user?.default_institution_id ?? null,
})

const profileForm = reactive(buildProfileForm(authStore.user))
const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmNewPassword: ''
})
const recoveryCodeStatus = ref({
  configured: false,
  remaining_count: 0,
  used_count: 0,
  total_count: 0,
})
const recoveryCodePassword = ref('')
const recoveryCodeLoading = ref(false)
const generatedRecoveryCodes = ref([])
const recoveryCodesSaved = ref(false)

const newCredential = reactive({
  name: '',
  environment: 'sandbox',
  token: '',
})
const credentials = ref([])
const activeCredentials = ref({ sandbox: null, production: null })
const incomingShares = ref([])
const outgoingShares = ref([])
const shareEmails = reactive({})

const profileSaving = ref(false)
const passwordSaving = ref(false)
const credentialLoading = ref(false)
const institutionQuery = ref(profileForm.affiliation || '')
const institutionSuggestions = ref([])
const institutionDropdownOpen = ref(false)
const affiliationSaving = ref(false)
const similarInstitutions = ref([])
let institutionSearchTimer = null

const passwordChangeRequired = computed(() => {
  return Boolean(authStore.user?.force_password_change || route.query.passwordChangeRequired)
})

watch(
  () => authStore.user,
  (nextUser) => {
    Object.assign(profileForm, buildProfileForm(nextUser))
    institutionQuery.value = nextUser?.affiliation || ''
  },
  { immediate: true, deep: true }
)

const memberSince = computed(() => {
  const createdAt = authStore.user?.created_at
  if (!createdAt) return 'N/A'
  return new Date(createdAt).toLocaleDateString()
})

const userInitials = computed(() => {
  const source = authStore.user?.display_name || authStore.user?.full_name || authStore.user?.email || 'user'
  return source
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
})

const profileChanged = computed(() => {
  const current = buildProfileForm(authStore.user)
  return JSON.stringify(current) !== JSON.stringify({
    email: profileForm.email || '',
    slug: profileForm.slug || '',
    display_name: profileForm.display_name || '',
    full_name: profileForm.full_name || '',
    affiliation: profileForm.affiliation || '',
    orcid: profileForm.orcid || '',
    bio: profileForm.bio || '',
    website_url: profileForm.website_url || '',
    avatar_url: profileForm.avatar_url || '',
    profile_visibility: profileForm.profile_visibility || 'private',
    show_email: Boolean(profileForm.show_email),
    show_orcid: Boolean(profileForm.show_orcid),
    show_affiliation: Boolean(profileForm.show_affiliation),
    default_institution_id: profileForm.default_institution_id ?? null,
  })
})

const resetPasswordForm = () => {
  passwordForm.currentPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmNewPassword = ''
}

const applyAffiliationResponse = (response) => {
  const payload = response.data || {}
  authStore.setUser({
    ...(authStore.user || {}),
    ...(payload.user || {}),
    institutions: payload.institutions || authStore.institutions,
    memberships: payload.memberships || authStore.memberships,
    default_institution: payload.institution || authStore.user?.default_institution || null,
  })
  Object.assign(profileForm, buildProfileForm(authStore.user))
  institutionQuery.value = profileForm.affiliation || payload.institution?.name || ''
  institutionSuggestions.value = []
  similarInstitutions.value = []
  institutionDropdownOpen.value = false
}

const loadInstitutionSuggestions = async () => {
  const query = institutionQuery.value.trim()
  profileForm.affiliation = query
  similarInstitutions.value = []
  if (query.length < 2) {
    institutionSuggestions.value = []
    institutionDropdownOpen.value = false
    return
  }
  try {
    const response = await institutionService.suggestInstitutions(query, { limit: 8 })
    institutionSuggestions.value = response.data?.institutions || []
    institutionDropdownOpen.value = institutionSuggestions.value.length > 0
  } catch (error) {
    console.error('Failed to load institution suggestions:', error)
  }
}

const scheduleInstitutionSuggestions = () => {
  if (institutionSearchTimer) {
    window.clearTimeout(institutionSearchTimer)
  }
  institutionSearchTimer = window.setTimeout(loadInstitutionSuggestions, 200)
}

const openInstitutionSuggestions = () => {
  if (institutionSuggestions.value.length) {
    institutionDropdownOpen.value = true
    return
  }
  scheduleInstitutionSuggestions()
}

const selectInstitution = async (institution) => {
  if (!institution?.id) return
  affiliationSaving.value = true
  try {
    const response = await institutionService.configureAffiliation({ institution_id: institution.id })
    applyAffiliationResponse(response)
    toast.success('Institutional affiliation updated')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update affiliation')
  } finally {
    affiliationSaving.value = false
  }
}

const createAffiliation = async (confirmCreate = false) => {
  const name = institutionQuery.value.trim()
  if (!name) return
  affiliationSaving.value = true
  try {
    const response = await institutionService.configureAffiliation({ name, confirm_create: Boolean(confirmCreate) })
    applyAffiliationResponse(response)
    toast.success(response.data?.created ? 'Institution created and assigned' : 'Institutional affiliation updated')
  } catch (error) {
    const details = error?.error?.details || error?.details || {}
    if (error?.error?.code === 'SIMILAR_INSTITUTION_EXISTS' && Array.isArray(details.similar)) {
      similarInstitutions.value = details.similar
      institutionDropdownOpen.value = false
    } else {
      toast.error(error?.error?.message || error?.message || 'Failed to update affiliation')
    }
  } finally {
    affiliationSaving.value = false
  }
}

const loadCredentials = async () => {
  try {
    const response = await authService.listZenodoCredentials()
    credentials.value = response.data?.credentials || []
    activeCredentials.value = response.data?.active || { sandbox: null, production: null }
    incomingShares.value = response.data?.incoming_shares || []
    outgoingShares.value = response.data?.outgoing_shares || []
  } catch (error) {
    console.error('Failed to load Zenodo credentials:', error)
  }
}

const loadRecoveryCodes = async () => {
  try {
    const response = await authService.getRecoveryCodes()
    recoveryCodeStatus.value = response.data?.recovery_codes || recoveryCodeStatus.value
  } catch (error) {
    console.error('Failed to load recovery code status:', error)
  }
}

const handleProfileUpdate = async () => {
  if (!profileChanged.value) return

  profileSaving.value = true
  try {
    await authStore.updateCurrentUser({
      email: profileForm.email,
      slug: profileForm.slug,
      display_name: profileForm.display_name,
      full_name: profileForm.full_name,
      affiliation: profileForm.affiliation,
      orcid: profileForm.orcid,
      bio: profileForm.bio,
      website_url: profileForm.website_url,
      avatar_url: profileForm.avatar_url,
      profile_visibility: profileForm.profile_visibility,
      show_email: profileForm.show_email,
      show_orcid: profileForm.show_orcid,
      show_affiliation: profileForm.show_affiliation,
      default_institution_id: profileForm.default_institution_id,
    })
    toast.success('Profile updated successfully')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update profile')
  } finally {
    profileSaving.value = false
  }
}

const handlePasswordUpdate = async () => {
  if (passwordForm.newPassword !== passwordForm.confirmNewPassword) {
    toast.error('New password and confirmation do not match')
    return
  }

  passwordSaving.value = true
  try {
    await authStore.updatePassword(
      passwordForm.currentPassword,
      passwordForm.newPassword,
      passwordForm.confirmNewPassword
    )
    toast.success('Password updated successfully')
    resetPasswordForm()
    if (!authStore.user?.force_password_change) {
      await Promise.all([loadCredentials(), loadRecoveryCodes()])
    }
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update password')
  } finally {
    passwordSaving.value = false
  }
}

const handleRecoveryCodeRegeneration = async () => {
  recoveryCodeLoading.value = true
  generatedRecoveryCodes.value = []
  try {
    const response = await authService.regenerateRecoveryCodes(recoveryCodePassword.value)
    recoveryCodeStatus.value = response.data?.recovery_codes || recoveryCodeStatus.value
    generatedRecoveryCodes.value = response.data?.codes || []
    recoveryCodesSaved.value = false
    recoveryCodePassword.value = ''
    toast.success('Recovery codes generated')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to generate recovery codes')
  } finally {
    recoveryCodeLoading.value = false
  }
}

const recoveryCodeText = computed(() => generatedRecoveryCodes.value.join('\n'))

const copyRecoveryCodes = async () => {
  if (!recoveryCodeText.value) return
  try {
    await navigator.clipboard.writeText(recoveryCodeText.value)
    toast.success('Recovery codes copied')
  } catch (error) {
    toast.error('Could not copy recovery codes')
  }
}

const downloadRecoveryCodes = () => {
  if (!recoveryCodeText.value) return
  const blob = new Blob([`${recoveryCodeText.value}\n`], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'webhdp-recovery-codes.txt'
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

const clearGeneratedRecoveryCodes = () => {
  if (!recoveryCodesSaved.value) return
  generatedRecoveryCodes.value = []
  recoveryCodesSaved.value = false
}

const formatEnvironment = (environment) => {
  const normalized = String(environment || '').trim().toLowerCase()
  if (normalized === 'sandbox') return 'Sandbox'
  if (normalized === 'production') return 'Production'
  return normalized || 'Zenodo'
}

const credentialsByEnvironment = (environment) => {
  return credentials.value.filter((credential) => credential.environment === environment)
}

const activeCredential = (environment) => {
  return activeCredentials.value?.[environment] || credentials.value.find((credential) => credential.environment === environment && credential.active) || null
}

const createCredential = async () => {
  credentialLoading.value = true
  try {
    await authService.createZenodoCredential({
      name: newCredential.name,
      environment: newCredential.environment,
      token: newCredential.token,
    })
    newCredential.name = ''
    newCredential.token = ''
    await loadCredentials()
    toast.success('Zenodo key added')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to add Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const validateCredentialById = async (credentialId) => {
  credentialLoading.value = true
  try {
    await authService.validateZenodoCredentialById(credentialId)
    await loadCredentials()
    toast.success('Zenodo key validated')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to validate Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const deleteCredentialById = async (credentialId) => {
  credentialLoading.value = true
  try {
    await authService.deleteZenodoCredentialById(credentialId)
    await loadCredentials()
    toast.success('Zenodo key deleted')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to delete Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const setActiveCredential = async (credential) => {
  credentialLoading.value = true
  try {
    await authService.setActiveZenodoCredential(credential.environment, credential.id)
    await loadCredentials()
    toast.success(`${formatEnvironment(credential.environment)} active key updated`)
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to set active Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const shareCredential = async (credential) => {
  credentialLoading.value = true
  try {
    await authService.shareZenodoCredential(credential.id, shareEmails[credential.id])
    shareEmails[credential.id] = ''
    await loadCredentials()
    toast.success('Zenodo key share invitation sent')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to share Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const acceptShare = async (shareId) => {
  credentialLoading.value = true
  try {
    await authService.acceptZenodoCredentialShare(shareId)
    await loadCredentials()
    toast.success('Shared Zenodo key accepted')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to accept shared Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

const declineShare = async (shareId) => {
  credentialLoading.value = true
  try {
    await authService.declineZenodoCredentialShare(shareId)
    await loadCredentials()
    toast.success('Shared Zenodo key declined')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to decline shared Zenodo key')
  } finally {
    credentialLoading.value = false
  }
}

if (!passwordChangeRequired.value) {
  loadCredentials()
  loadRecoveryCodes()
}
</script>
