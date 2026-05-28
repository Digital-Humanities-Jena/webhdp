<template>
  <router-view v-if="isPipelineConstructorRoute" />

  <div v-else class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="lg:grid lg:grid-cols-12 lg:gap-x-5">
      <aside class="py-6 px-2 sm:px-6 lg:py-0 lg:px-0 lg:col-span-3">
        <nav class="space-y-1">
          <router-link
            v-for="item in navigation"
            :key="item.name"
            :to="item.href"
            :class="[
              isActive(item.href)
                ? 'bg-gray-50 text-indigo-700 hover:text-indigo-700 hover:bg-white'
                : 'text-gray-900 hover:text-gray-900 hover:bg-gray-50',
              'group rounded-md px-3 py-2 flex items-center text-sm font-medium'
            ]"
            :aria-current="isActive(item.href) ? 'page' : undefined"
          >
            <component
              :is="item.icon"
              :class="[
                isActive(item.href)
                  ? 'text-indigo-500 group-hover:text-indigo-500'
                  : 'text-gray-400 group-hover:text-gray-500',
                'flex-shrink-0 -ml-1 mr-3 h-6 w-6'
              ]"
              aria-hidden="true"
            />
            <span class="truncate">{{ item.name }}</span>
          </router-link>
        </nav>
      </aside>

      <div class="space-y-6 sm:px-6 lg:px-0 lg:col-span-9">
        <router-view></router-view>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  AdjustmentsHorizontalIcon,
  CircleStackIcon,
  DocumentDuplicateIcon,
  CloudIcon,
  ServerIcon,
  BellAlertIcon,
  ShieldCheckIcon,
} from '@heroicons/vue/24/outline'

const route = useRoute()
const isPipelineConstructorRoute = computed(() => route.name === 'PipelineConfig')

const navigation = [
  { name: 'Pipelines', href: '/settings/pipelines', icon: AdjustmentsHorizontalIcon },
  { name: 'EDM Config', href: '/settings/edm', icon: CircleStackIcon },
  { name: 'EDM Templates', href: '/settings/edm-templates', icon: DocumentDuplicateIcon },
  { name: 'Cloud Testing', href: '/settings/cloud-testing', icon: CloudIcon },
  { name: 'Storage Priority', href: '/settings/storage', icon: ServerIcon },
  { name: 'Login MFA', href: '/settings/mfa', icon: ShieldCheckIcon },
  { name: 'Modality Detection', href: '/settings/modalities', icon: AdjustmentsHorizontalIcon },
  { name: 'Credentials Status', href: '/settings/observability/credentials', icon: CloudIcon },
  { name: 'API Activity', href: '/settings/observability/api-activity', icon: ServerIcon },
  { name: 'Notification Delivery', href: '/settings/observability/notifications', icon: BellAlertIcon },
]

const isActive = (href) => {
  return route.path.startsWith(href)
}
</script>
