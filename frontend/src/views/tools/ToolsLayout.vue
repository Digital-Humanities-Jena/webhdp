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
        <nav class="flex gap-2 overflow-x-auto pb-2 lg:block lg:space-y-1 lg:overflow-visible lg:pb-0">
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

          <div
            v-for="item in disabledItems"
            :key="item.name"
            :data-testid="`tools-nav-disabled-${item.featureKey}`"
            class="group hidden rounded-md px-3 py-2 text-sm font-medium bg-gray-50 text-gray-400 cursor-not-allowed lg:flex lg:items-center"
            :title="item.disabledReason || 'Unavailable'"
          >
            <component
              :is="item.icon"
              class="flex-shrink-0 -ml-1 mr-3 h-6 w-6 text-gray-300"
              aria-hidden="true"
            />
            <div class="min-w-0 flex-1">
              <span class="block truncate">{{ item.name }}</span>
              <span class="mt-0.5 block text-[11px] font-normal text-gray-400">{{ item.disabledReason || 'Unavailable' }}</span>
            </div>
            <span class="ml-auto text-[10px] uppercase tracking-wide">Disabled</span>
          </div>
        </nav>

        <div
          v-if="disabledItems.length > 0"
          class="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 lg:mt-4"
        >
          <span class="lg:hidden">{{ disabledItems.length }} tools hidden on this screen are disabled by role, capability, or runtime.</span>
          <span class="hidden lg:inline">Some tools are disabled because of role, capability, or runtime requirements.</span>
        </div>
      </aside>

      <div class="mt-6 space-y-6 lg:mt-0 lg:col-span-9">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
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
const context = ref({
  features: {}
})
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

const navigation = computed(() => rawNavigation.map((item) => {
  const feature = context.value.features?.[item.featureKey] || {}
  return {
    ...item,
    enabled: !!feature.enabled,
    disabledReason: feature.reason || 'Unavailable'
  }
}))

const enabledItems = computed(() => navigation.value.filter((item) => item.enabled))
const disabledItems = computed(() => context.value.core_only ? [] : navigation.value.filter((item) => !item.enabled))

const isActive = (href) => route.path.startsWith(href)

const loadContext = async () => {
  try {
    const response = await toolsService.getContext()
    context.value = response.data || context.value
  } catch (e) {
    context.value = { features: {} }
  }
}

onMounted(loadContext)
</script>
