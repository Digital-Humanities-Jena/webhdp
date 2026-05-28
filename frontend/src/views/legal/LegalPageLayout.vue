<template>
  <main class="min-h-screen bg-gray-50 text-gray-900">
    <header class="border-b border-gray-200 bg-white">
      <div class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <router-link to="/" class="text-lg font-semibold tracking-tight text-gray-950">WebHDP</router-link>
        <LegalLinks />
      </div>
    </header>

    <section class="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <div class="mb-8">
        <p v-if="eyebrow" class="text-xs font-semibold uppercase tracking-wide text-indigo-700">{{ eyebrow }}</p>
        <h1 class="mt-2 text-3xl font-bold tracking-tight text-gray-950 sm:text-4xl">{{ title }}</h1>
        <p v-if="updated" class="mt-3 text-sm text-gray-500">Last updated: {{ updated }}</p>
      </div>

      <article class="space-y-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <slot />
      </article>
    </section>
  </main>
</template>

<script setup>
import LegalLinks from '@/components/legal/LegalLinks.vue'

defineProps({
  eyebrow: {
    type: String,
    default: '',
  },
  title: {
    type: String,
    required: true,
  },
  updated: {
    type: String,
    default: '30 April 2026',
  },
})
</script>
