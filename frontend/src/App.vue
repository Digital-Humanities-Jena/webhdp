<template>
  <div id="app">
    <router-view />
    <CookieNotice />
    <ToastContainer />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import CookieNotice from '@/components/legal/CookieNotice.vue'
import ToastContainer from '@/components/ui/ToastContainer.vue'

const authStore = useAuthStore()

onMounted(() => {
  const publicPath = typeof window !== 'undefined' && (
    window.location.pathname.startsWith('/p/records/')
    || window.location.pathname.startsWith('/embed/records/')
    || window.location.pathname === '/'
    || ['/credits', '/impressum', '/privacy', '/cookies'].includes(window.location.pathname)
  )
  if (publicPath) {
    return
  }
  // Fetch current user if token exists
  if (authStore.token) {
    // The store clears expired authentication while retaining user-scoped drafts.
    authStore.fetchCurrentUser().catch(() => {})
  }
})
</script>

<style>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
</style>
