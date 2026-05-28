<template>
  <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div v-if="loading" class="py-16">
      <LoadingSpinner text="Loading profile..." />
    </div>

    <div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {{ error }}
    </div>

    <section v-else-if="profile" class="space-y-6">
      <div class="flex items-center gap-4">
        <img
          v-if="profile.logo_url"
          :src="profile.logo_url"
          :alt="profile.name"
          class="h-16 w-16 rounded-lg object-cover border border-gray-200 bg-white"
        />
        <div v-else class="h-16 w-16 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center text-xl font-semibold">
          {{ initials }}
        </div>
        <div>
          <h1 class="text-2xl font-semibold text-gray-900">{{ profile.name }}</h1>
          <p v-if="profile.slug" class="text-sm text-gray-500">{{ profile.slug }}</p>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <article class="lg:col-span-2 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 class="text-lg font-semibold text-gray-900">Institution</h2>
          <p v-if="profile.description" class="mt-3 text-sm leading-6 text-gray-700">{{ profile.description }}</p>
          <p v-else class="mt-3 text-sm text-gray-500">No description available.</p>
        </article>

        <aside class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 class="text-lg font-semibold text-gray-900">Details</h2>
          <dl class="mt-4 space-y-3 text-sm">
            <div v-if="profile.legal_name">
              <dt class="text-gray-500">Legal name</dt>
              <dd class="font-medium text-gray-900">{{ profile.legal_name }}</dd>
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

const initials = computed(() => (profile.value?.name || 'Institution').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase())

async function loadProfile() {
  loading.value = true
  error.value = ''
  profile.value = null
  try {
    const response = await profileService.getInstitutionProfile(route.params.identifier)
    profile.value = response.data?.institution || null
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
