<template>
  <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div v-if="loading" class="py-16">
      <LoadingSpinner text="Loading profile..." />
    </div>

    <div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {{ error }}
    </div>

    <section v-else-if="profile" class="space-y-6">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex items-center gap-4">
          <img
            v-if="profile.avatar_url"
            :src="profile.avatar_url"
            :alt="profileName"
            class="h-16 w-16 rounded-full object-cover border border-gray-200"
          />
          <div v-else class="h-16 w-16 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xl font-semibold">
            {{ initials }}
          </div>
          <div>
            <h1 class="text-2xl font-semibold text-gray-900">{{ profileName }}</h1>
            <p v-if="profile.slug" class="text-sm text-gray-500">@{{ profile.slug }}</p>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <article class="lg:col-span-2 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 class="text-lg font-semibold text-gray-900">Profile</h2>
          <p v-if="profile.bio" class="mt-3 text-sm leading-6 text-gray-700">{{ profile.bio }}</p>
          <p v-else class="mt-3 text-sm text-gray-500">No bio available.</p>
        </article>

        <aside class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 class="text-lg font-semibold text-gray-900">Details</h2>
          <dl class="mt-4 space-y-3 text-sm">
            <div v-if="profile.full_name">
              <dt class="text-gray-500">Full name</dt>
              <dd class="font-medium text-gray-900">{{ profile.full_name }}</dd>
            </div>
            <div v-if="profile.affiliation">
              <dt class="text-gray-500">Affiliation</dt>
              <dd class="font-medium text-gray-900">{{ profile.affiliation }}</dd>
            </div>
            <div v-if="profile.orcid">
              <dt class="text-gray-500">ORCID</dt>
              <dd class="font-medium text-gray-900">{{ profile.orcid }}</dd>
            </div>
            <div v-if="profile.email">
              <dt class="text-gray-500">Email</dt>
              <dd class="font-medium text-gray-900">{{ profile.email }}</dd>
            </div>
            <div v-if="profile.website_url">
              <dt class="text-gray-500">Website</dt>
              <dd>
                <a :href="profile.website_url" class="font-medium text-indigo-600 hover:text-indigo-700" target="_blank" rel="noopener noreferrer">
                  {{ profile.website_url }}
                </a>
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import profileService from '@/services/profile.service'

const route = useRoute()
const loading = ref(false)
const error = ref('')
const profile = ref(null)

const profileName = computed(() => profile.value?.display_name || profile.value?.full_name || profile.value?.slug || 'User profile')
const initials = computed(() => profileName.value.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase())

async function loadProfile() {
  loading.value = true
  error.value = ''
  profile.value = null
  try {
    const response = await profileService.getUserProfile(route.params.identifier)
    profile.value = response.data?.user || null
    if (!profile.value) {
      error.value = 'Profile was not found.'
    }
  } catch (err) {
    error.value = err?.error?.message || err?.message || 'Profile was not found.'
  } finally {
    loading.value = false
  }
}

onMounted(loadProfile)
watch(() => route.params.identifier, loadProfile)
</script>
