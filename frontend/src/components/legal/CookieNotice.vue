<template>
  <section
    v-if="visible"
    class="fixed inset-x-0 bottom-0 z-50 border-t border-gray-200 bg-white/95 px-4 py-4 shadow-2xl backdrop-blur sm:px-6"
    aria-label="Cookies and storage notice"
  >
    <div class="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="max-w-3xl text-sm leading-6 text-gray-700">
        <p>
          WebHDP uses necessary browser storage for authentication, workflow recovery, issue drafts, and this notice.
          It does not use non-essential tracking cookies by default.
        </p>
        <p class="mt-1 text-xs text-gray-500">
          Read the
          <router-link to="/privacy" class="font-medium text-indigo-700 hover:text-indigo-900">Privacy Policy</router-link>
          and
          <router-link to="/cookies" class="font-medium text-indigo-700 hover:text-indigo-900">Cookies and Storage Notice</router-link>.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex shrink-0 items-center justify-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
        @click="dismiss"
      >
        OK
      </button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const STORAGE_KEY = 'webhdp_cookie_notice_v1'
const visible = ref(false)

function storageAvailable() {
  try {
    return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
  } catch {
    return false
  }
}

onMounted(() => {
  if (!storageAvailable()) {
    visible.value = true
    return
  }
  visible.value = window.localStorage.getItem(STORAGE_KEY) !== 'accepted'
})

function dismiss() {
  visible.value = false
  if (!storageAvailable()) return
  try {
    window.localStorage.setItem(STORAGE_KEY, 'accepted')
  } catch {
    // Ignore storage write failures; the notice has still been acknowledged for this render.
  }
}
</script>
