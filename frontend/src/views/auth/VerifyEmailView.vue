<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
      <div>
        <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Email Verification
        </h2>
      </div>

      <div v-if="verifying" class="text-center">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto"></div>
        <p class="mt-4 text-gray-600">Verifying your email address...</p>
      </div>

      <div v-else-if="success" class="bg-green-50 border border-green-400 text-green-700 px-4 py-3 rounded text-center">
        <p class="font-bold">Email verified successfully!</p>
        <p class="mt-2">You can now sign in to your account.</p>
        <div class="mt-4">
          <router-link to="/login" class="text-indigo-600 hover:text-indigo-500 font-medium">
            Go to Login
          </router-link>
        </div>
      </div>

      <div v-else class="bg-red-50 border border-red-400 text-red-700 px-4 py-3 rounded text-center">
        <p class="font-bold">Verification failed</p>
        <p class="mt-2">{{ error || 'The verification link is invalid or has expired.' }}</p>
        <div class="mt-4">
          <router-link to="/register" class="text-indigo-600 hover:text-indigo-500 font-medium">
            Try registering again
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const verifying = ref(true)
const success = ref(false)
const error = ref('')

onMounted(async () => {
  const token = route.params.token
  if (!token) {
    error.value = 'No verification token provided.'
    verifying.value = false
    return
  }

  try {
    const apiBase = import.meta.env.VITE_API_URL || '/api/v1'
    await axios.get(`${apiBase}/auth/verify-email/${token}`)
    success.value = true
  } catch (err) {
    error.value = err.response?.data?.error || 'Verification failed.'
  } finally {
    verifying.value = false
  }
})
</script>
