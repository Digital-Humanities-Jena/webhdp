import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/styles/main.css'
import { registerServiceWorker } from './pwa'

const app = createApp(App)
const pinia = createPinia()

// CRITICAL: Initialize Pinia FIRST
app.use(pinia)

// THEN restore token to auth store
import { useAuthStore } from '@/stores/auth'
const authStore = useAuthStore()

// The token is already loaded in the store from localStorage
// But we need to ensure it's available before routing
if (authStore.token) {
  console.log('Token found and restored:', authStore.token.substring(0, 20) + '...')
}

// Now initialize router
app.use(router)
app.mount('#app')
registerServiceWorker()
