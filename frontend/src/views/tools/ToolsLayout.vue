<template>
  <router-view v-if="isPipelineConstructorRoute" />

  <div v-else class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900">Tools</h1>
      <p class="mt-1 text-sm text-gray-600">
        Operational utilities for preflight checks, metadata QA, and runtime maintenance.
      </p>
    </div>

    <div class="lg:grid lg:grid-cols-12 lg:gap-x-5">
      <aside class="py-2 lg:py-0 lg:col-span-3">
        <nav aria-label="Available tools" class="flex gap-2 overflow-x-auto pb-2 lg:block lg:space-y-1 lg:overflow-visible lg:pb-0">
          <router-link
            v-for="item in enabledItems"
            :key="item.name"
            :to="item.href"
            :data-testid="`tools-nav-enabled-${item.featureKey}`"
            :class="[
              isActive(item.href)
                ? 'bg-gray-50 text-indigo-700 hover:text-indigo-700 hover:bg-white'
                : 'text-gray-900 hover:text-gray-900 hover:bg-gray-50',
              'group rounded-md px-3 py-2 flex min-w-max items-center text-sm font-medium lg:min-w-0'
            ]"
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

        <details v-if="disabledItems.length" class="mt-3 rounded-md border border-gray-200 bg-white p-3 text-sm text-gray-700">
          <summary class="cursor-pointer font-medium">Unavailable tools ({{ disabledItems.length }})</summary>
          <ul class="mt-2 space-y-2">
            <li v-for="item in disabledItems" :key="item.name" :data-testid="`tools-nav-disabled-${item.featureKey}`">
              <router-link v-if="item.href === '/tools/pipeline-preflight'" :to="item.href" class="font-medium text-indigo-700 underline">{{ item.name }}</router-link>
              <span v-else class="font-medium">{{ item.name }}</span>
              <p class="text-xs text-gray-600">{{ item.disabledReason }}</p>
            </li>
          </ul>
        </details>
      </aside>

      <div class="mt-6 space-y-6 lg:mt-0 lg:col-span-9">
        <router-view v-if="!isToolsIndex" />
        <div v-else class="rounded-lg bg-white p-6 shadow">
          <p v-if="contextError" role="alert" class="text-sm text-gray-700">Could not load available tools.</p>
          <p v-else-if="!context || enabledItems.length" role="status" class="text-sm text-gray-600">Loading available tools…</p>
          <p v-else class="text-sm text-gray-700">No tools are available for your account on this deployment.</p>
          <button v-if="contextError" type="button" class="mt-3 text-sm text-indigo-700 underline" @click="loadContext">Try again</button>
          <router-link v-else-if="context && !enabledItems.length" to="/uploads" class="mt-3 inline-block text-sm text-indigo-700 underline">Open Uploads</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, provide, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BeakerIcon,
  ClipboardDocumentCheckIcon,
  WrenchScrewdriverIcon,
  SparklesIcon,
  DocumentMagnifyingGlassIcon,
  CpuChipIcon,
  ArrowDownTrayIcon,
  TrashIcon,
  RectangleStackIcon,
} from '@heroicons/vue/24/outline'
import toolsService from '@/services/tools.service'

const route = useRoute()
const router = useRouter()
const context = ref(null)
const contextError = ref(false)
const isToolsIndex = computed(() => route.name === 'ToolsOverview')
const isPipelineConstructorRoute = computed(() => route.name === 'PipelineConstructor')

const rawNavigation = [
  {
    name: 'Playground',
    href: '/tools/playground',
    icon: BeakerIcon,
    featureKey: 'native_playground'
  },
  {
    name: 'Pipeline Constructor',
    href: '/tools/pipeline-constructor',
    icon: RectangleStackIcon,
    featureKey: 'pipeline_constructor'
  },
  {
    name: 'Pipeline Preflight',
    href: '/tools/pipeline-preflight',
    icon: ClipboardDocumentCheckIcon,
    featureKey: 'pipeline_preflight'
  },
  {
    name: 'MSF Validator (Local)',
    href: '/tools/msf-validator-local',
    icon: WrenchScrewdriverIcon,
    featureKey: 'pipeline_preflight'
  },
  {
    name: 'MSF Reference Repair',
    href: '/tools/msf-reference-repair',
    icon: WrenchScrewdriverIcon,
    featureKey: 'msf_reference_repair'
  },
  {
    name: 'Metadata Normalizer',
    href: '/tools/metadata-normalizer',
    icon: SparklesIcon,
    featureKey: 'metadata_normalizer'
  },
  {
    name: 'Output Preview QA',
    href: '/tools/output-preview-qa',
    icon: DocumentMagnifyingGlassIcon,
    featureKey: 'output_preview_qa'
  },
  {
    name: 'HPC Diagnostics',
    href: '/tools/hpc-diagnostics',
    icon: CpuChipIcon,
    featureKey: 'hpc_diagnostics'
  },
  {
    name: 'HDP Component Installer',
    href: '/tools/hdp-components/install',
    icon: ArrowDownTrayIcon,
    featureKey: 'hdp_component_installer'
  },
  {
    name: 'Session Cleanup',
    href: '/tools/session-cleanup',
    icon: TrashIcon,
    featureKey: 'session_cleanup'
  },
  {
    name: 'Zenodo Batch Ops',
    href: '/tools/zenodo-batch-operations',
    icon: RectangleStackIcon,
    featureKey: 'zenodo_batch_operations'
  },
  {
    name: 'Zenodo Account Retrieval',
    href: '/tools/zenodo-account-retrieval',
    icon: ArrowDownTrayIcon,
    featureKey: 'zenodo_account_retrieval'
  },
  {
    name: 'Zenodo OAI Harvest',
    href: '/tools/zenodo-oai-harvest',
    icon: ArrowDownTrayIcon,
    featureKey: 'zenodo_oai_harvest'
  },
  {
    name: 'Community Moderation',
    href: '/tools/community-moderation',
    icon: RectangleStackIcon,
    featureKey: 'community_moderation'
  },
  {
    name: 'Community Migration',
    href: '/tools/community-migration',
    icon: RectangleStackIcon,
    featureKey: 'community_migration'
  }
]

const navigation = computed(() => context.value ? rawNavigation.map((item) => {
  const feature = context.value.features?.[item.featureKey] || {}
  return {
    ...item,
    enabled: !!feature.enabled,
    disabledReason: feature.reason || 'Unavailable'
  }
}) : [])

const enabledItems = computed(() => navigation.value.filter((item) => item.enabled))
const disabledItems = computed(() => navigation.value.filter((item) => !item.enabled))

const isActive = (href) => route.path.startsWith(href)

const loadContext = async () => {
  contextError.value = false
  try {
    const response = await toolsService.getContext()
    context.value = response.data || null
    contextError.value = !context.value
  } catch {
    contextError.value = true
  }
}

provide('tools-context', { context, contextError, loadContext })

watchEffect(() => {
  if (isToolsIndex.value && enabledItems.value.length) {
    void router.replace({ path: enabledItems.value[0].href, query: route.query, hash: route.hash })
  }
})

onMounted(loadContext)
</script>
