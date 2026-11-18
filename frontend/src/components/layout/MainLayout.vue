<template>
  <div class="min-h-screen bg-gray-50">
    <a href="#main-content" class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-white focus:p-3 focus:text-indigo-700">Skip to content</a>
    <nav v-if="publicationOnly" aria-label="Main navigation" class="border-b border-gray-200 bg-white">
      <div class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <router-link to="/model-publication" class="text-lg font-semibold text-gray-900 hover:text-indigo-700">
          WebHDP
        </router-link>
        <div class="flex items-center gap-4">
          <router-link to="/model-publication/samples" class="text-sm font-medium text-indigo-700 hover:underline">
            Sample downloads
          </router-link>
          <button type="button" class="rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50" @click="handleLogout">
            Sign out
          </button>
        </div>
      </div>
    </nav>
    <nav v-else aria-label="Main navigation" class="sticky top-0 z-40 border-b border-gray-200 bg-white/95 backdrop-blur">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex min-h-[64px] flex-wrap items-center justify-between gap-3 py-3">
          <div class="flex items-center gap-3 min-w-0">
            <router-link
              to="/workflow/upload"
              class="text-lg font-semibold tracking-tight text-gray-900 hover:text-indigo-700 transition-colors"
            >
              WebHDP
            </router-link>
            <span class="hidden sm:inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-gray-600">
              {{ roleLabel }}
            </span>
            <router-link
              to="/workflow/upload"
              class="inline-flex items-center rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700"
            >
              + New Upload
            </router-link>
          </div>

          <div class="flex items-center gap-2 sm:gap-3">
            <div v-if="authStore.user?.role === 'admin' && versionInfo" class="hidden md:flex flex-col items-end">
              <span class="text-[10px] font-mono text-gray-400 leading-none">v{{ versionInfo.version }}</span>
              <span class="text-[9px] font-mono text-gray-300 leading-none mt-0.5">
                {{ formatTimestamp(versionInfo.timestamp) }}
              </span>
            </div>
            <router-link
              to="/issues/report"
              class="rounded-md border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:border-rose-300 hover:bg-rose-100 hover:text-rose-900"
              @click.prevent="handleReportIssue"
            >
              Report Issue
            </router-link>
            <router-link
              to="/account/configuration"
              class="rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
            >
              Account
            </router-link>
            <NotificationBell />
            <span v-if="authStore.user" class="hidden lg:inline max-w-[220px] truncate text-xs text-gray-500">
              {{ authStore.user.email }}
            </span>
            <button
              @click="handleLogout"
              class="rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
            >
              Logout
            </button>
          </div>
        </div>

        <div class="pb-3">
          <div class="flex items-center gap-1.5 overflow-x-auto">
            <router-link
              v-for="item in navigationItems"
              :key="item.to"
              :to="item.to"
              custom
              v-slot="{ href, navigate, isActive }"
            >
              <a
                :href="href"
                :aria-current="isActive || isRouteActive(item.to) ? 'page' : undefined"
                @click="navigate"
                :class="[
                  'whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
                  isActive || isRouteActive(item.to)
                    ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                    : 'border-transparent bg-gray-100 text-gray-700 hover:border-gray-200 hover:bg-white hover:text-gray-900'
                ]"
              >
                {{ item.label }}
              </a>
            </router-link>
          </div>
        </div>
      </div>
    </nav>

    <main id="main-content" tabindex="-1">
      <router-view :key="route.path" />
    </main>

    <footer class="border-t border-gray-200 bg-white px-4 py-5">
      <LegalLinks />
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import { useNotificationStore } from '@/stores/notifications'
import { buildIssueDraftContext, saveIssueDraftContext } from '@/utils/issueDraft'
import NotificationBell from '@/components/layout/NotificationBell.vue'
import LegalLinks from '@/components/legal/LegalLinks.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const notificationStore = useNotificationStore()
const versionInfo = ref(null)
const publicationOnly = computed(() => Boolean(authStore.user?.model_publication_only))

const API_URL = import.meta.env.VITE_API_URL || '/api/v1'

const fetchVersion = async () => {
  try {
    const response = await fetch(`${API_URL}/admin/version`, {
      headers: {
        'Authorization': `Bearer ${authStore.token}`
      }
    })
    const result = await response.json()
    if (result.success) {
      versionInfo.value = result.data
    }
  } catch (error) {
    console.error('Failed to fetch version:', error)
  }
}

const formatTimestamp = (ts) => {
  if (!ts) return ''
  try {
    const date = new Date(ts)
    return date.toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (e) {
    return ts
  }
}

const role = computed(() => authStore.user?.role || 'user')
const roleLabel = computed(() => {
  if (role.value === 'admin') return 'Admin'
  if (role.value === 'moderator') return 'Moderator'
  if (Array.isArray(authStore.user?.groups) && authStore.user.groups.includes('developer')) return 'Developer'
  return 'User'
})

const navigationItems = computed(() => {
  const items = [
    ...(authStore.user?.onboarding_required ? [{ label: 'First Steps', to: '/onboarding' }] : []),
    { label: 'Publish a 3D model', to: '/model-publication' },
    { label: 'Dashboard', to: '/dashboard' },
    { label: 'Uploads', to: '/uploads' },
    { label: 'Submissions', to: '/submissions' },
    { label: 'Issues', to: '/issues' },
    { label: 'Records Explorer', to: '/records/explorer' },
    { label: 'Datasets', to: '/datasets' },
    { label: 'HPC Access', to: '/hpc-resources' },
    { label: 'Linked processing', to: '/link/jobs' },
    { label: 'Connected Apps', to: '/account/connected-apps' },
    { label: 'Tools', to: '/tools' },
    { label: 'Docs', to: '/docs' }
  ]

  if ((authStore.institutions?.length || 0) > 0 || role.value === 'admin') {
    items.push({ label: 'Institutions', to: '/account/institutions' })
  }

  if (role.value === 'admin' || role.value === 'moderator') {
    items.push({
      label: role.value === 'admin' ? 'Admin Panel' : 'Review Panel',
      to: '/admin/dashboard'
    })
  }
  if (role.value === 'admin') {
    items.push({ label: 'Initial Setup', to: '/admin/setup' })
    items.push({ label: 'Sessions', to: '/admin/session-monitoring' })
    items.push({ label: 'HPC Admin', to: '/admin/hpc-access' })
    items.push({ label: 'WebHDP-Link', to: '/admin/webhdp-link' })
    items.push({ label: 'Settings', to: '/settings' })
  }
  if (
    role.value === 'admin' ||
    role.value === 'moderator' ||
    authStore.hasCapability('developer_access') ||
    authStore.hasGroup('developer')
  ) {
    items.push({ label: 'Developer', to: '/developer' })
  }
  if (systemStore.coreOnly) {
    const corePaths = new Set(["/onboarding", "/model-publication", "/dashboard", "/uploads", "/submissions", "/records/explorer", "/hpc-resources", "/tools", "/docs", "/admin/dashboard", "/account/connected-apps", "/admin/webhdp-link", "/link/jobs"])
    return items.filter((item) => corePaths.has(item.to))
  }
  return items
})

const isRouteActive = (targetPath) => {
  if (!targetPath) return false
  if (targetPath === '/tools') return route.path.startsWith('/tools')
  if (targetPath === '/link/jobs') return route.path === '/link/jobs' || route.path.startsWith('/link/jobs/')
  if (targetPath === '/settings') return route.path.startsWith('/settings')
  if (targetPath === '/docs') return route.path === '/docs' || route.path.startsWith('/docs/')
  if (targetPath === '/admin/setup') return route.path === '/admin/setup'
  if (targetPath === '/admin/dashboard') return route.path === '/admin/dashboard' || route.path.startsWith('/admin/review')
  return route.path === targetPath
}

onMounted(() => {
  if (authStore.user?.role === 'admin') {
    fetchVersion()
  }
  if (authStore.token && !publicationOnly.value) {
    notificationStore.startPolling()
  }
})

onBeforeUnmount(() => {
  notificationStore.stopPolling()
})

watch(
  () => authStore.user?.role,
  (nextRole) => {
    if (nextRole === 'admin' && !versionInfo.value) {
      fetchVersion()
    }
  }
)

watch(
  () => authStore.token,
  (nextToken) => {
    if (nextToken && !publicationOnly.value) {
      notificationStore.startPolling()
    } else {
      notificationStore.reset()
    }
  }
)

const handleLogout = () => {
  notificationStore.reset()
  authStore.logout()
  router.push('/login')
}

const handleReportIssue = () => {
  saveIssueDraftContext(buildIssueDraftContext({ route, user: authStore.user }))
  router.push('/issues/report')
}
</script>
