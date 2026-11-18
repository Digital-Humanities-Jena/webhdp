<template>
  <div class="min-h-screen bg-stone-50 text-slate-950">
    <header class="relative min-h-[76svh] overflow-hidden">
      <img
        :src="heroImage"
        alt=""
        aria-hidden="true"
        class="absolute inset-0 h-full w-full object-cover"
      />
      <div class="absolute inset-0 bg-white/76 lg:bg-[linear-gradient(90deg,rgba(255,255,255,0.94)_0%,rgba(255,255,255,0.86)_36%,rgba(255,255,255,0.42)_68%,rgba(255,255,255,0.18)_100%)]"></div>

      <nav class="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-4 py-5 sm:px-6 lg:px-8" aria-label="Public navigation">
        <router-link to="/" class="text-lg font-semibold tracking-tight text-slate-950">
          WebHDP
        </router-link>
        <div class="flex items-center gap-2">
          <router-link
            to="/model-publication/samples"
            class="rounded-md px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-white/70 hover:text-slate-950"
          >
            Sample models
          </router-link>
          <router-link
            to="/docs"
            class="hidden rounded-md px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-white/70 hover:text-slate-950 sm:inline-flex"
          >
            Docs
          </router-link>
          <router-link
            to="/login"
            class="rounded-md border border-slate-300 bg-white/80 px-3 py-2 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:border-slate-400 hover:bg-white"
          >
            Sign in
          </router-link>
        </div>
      </nav>

      <section class="relative z-10 mx-auto flex max-w-7xl px-4 pb-16 pt-12 sm:px-6 sm:pt-20 lg:px-8">
        <div class="max-w-3xl">
          <p class="text-sm font-semibold uppercase tracking-[0.18em] text-teal-700">
            Heritage Data Publishing
          </p>
          <h1 class="mt-5 max-w-2xl text-5xl font-bold leading-[1.02] tracking-normal text-slate-950 sm:text-6xl lg:text-7xl">
            WebHDP turns heritage datasets into publishable records.
          </h1>
          <p class="mt-6 max-w-2xl text-lg leading-8 text-slate-700 sm:text-xl">
            Prepare, validate, and publish heritage-science datasets with strong support for 3D assets, Zenodo records, EDM, IIIF, METS, and traceable provenance.
          </p>

          <div class="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            <router-link
              to="/register"
              class="inline-flex items-center justify-center rounded-md bg-teal-700 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-700 focus:ring-offset-2"
            >
              Register
              <ArrowRightIcon class="ml-2 h-4 w-4" aria-hidden="true" />
            </router-link>
            <router-link
              to="/login"
              class="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white/85 px-5 py-3 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:border-slate-400 hover:bg-white focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2"
            >
              Sign in
            </router-link>
            <router-link
              to="/docs"
              class="inline-flex items-center justify-center rounded-md px-4 py-3 text-sm font-semibold text-slate-700 transition-colors hover:bg-white/70 hover:text-slate-950"
            >
              View documentation
            </router-link>
          </div>
        </div>
      </section>
    </header>

    <main>
      <section class="border-y border-slate-200 bg-white">
        <div class="mx-auto grid max-w-7xl gap-0 px-4 sm:grid-cols-2 sm:px-6 lg:grid-cols-4 lg:px-8">
          <div
            v-for="metric in metrics"
            :key="metric.label"
            class="border-slate-200 py-6 sm:even:border-l lg:border-l lg:first:border-l-0"
          >
            <p class="text-2xl font-bold text-slate-950">{{ metric.value }}</p>
            <p class="mt-1 text-sm text-slate-600">{{ metric.label }}</p>
          </div>
        </div>
      </section>

      <section class="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8 lg:py-16">
        <div class="max-w-2xl">
          <h2 class="text-3xl font-bold tracking-normal text-slate-950">
            From raw assets to reusable publication packages.
          </h2>
          <p class="mt-4 text-base leading-7 text-slate-600">
            WebHDP keeps the workflow focused: ingest files, map metadata, validate standards output, and publish with a record of what happened.
          </p>
        </div>

        <div class="mt-10 grid gap-4 lg:grid-cols-2">
          <article
            v-for="item in workflowHighlights"
            :key="item.title"
            class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div class="flex items-start gap-4">
              <span class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-teal-50 text-teal-700 ring-1 ring-teal-100">
                <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h3 class="text-base font-semibold text-slate-950">{{ item.title }}</h3>
                <p class="mt-2 text-sm leading-6 text-slate-600">{{ item.description }}</p>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="border-y border-slate-200 bg-white">
        <div class="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-10 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div class="max-w-3xl">
            <p class="text-sm font-semibold uppercase tracking-wide text-teal-700">People and project context</p>
            <h2 class="mt-2 text-2xl font-bold tracking-normal text-slate-950">
              Developed in Digital Humanities and EU cultural heritage projects.
            </h2>
            <p class="mt-3 text-sm leading-6 text-slate-600">
              WebHDP credits its lead development, contributing developers, affiliations, and the EU project context behind the platform.
            </p>
          </div>
          <router-link
            to="/credits"
            class="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-teal-700 focus:ring-offset-2"
          >
            View credits
            <ArrowRightIcon class="ml-2 h-4 w-4" aria-hidden="true" />
          </router-link>
        </div>
      </section>

      <section class="bg-slate-950 text-white">
        <div class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-12 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div class="max-w-2xl">
            <h2 class="text-2xl font-bold tracking-normal">Ready to prepare a dataset?</h2>
            <p class="mt-3 text-sm leading-6 text-slate-300">
              Create an account to start a resumable WebHDP upload workflow, or sign in to continue an existing session.
            </p>
          </div>
          <div class="flex flex-col gap-3 sm:flex-row">
            <router-link
              to="/register"
              class="inline-flex items-center justify-center rounded-md bg-white px-5 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-teal-50"
            >
              Register
            </router-link>
            <router-link
              to="/login"
              class="inline-flex items-center justify-center rounded-md border border-white/25 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/10"
            >
              Sign in
            </router-link>
          </div>
        </div>
      </section>
    </main>

    <footer class="border-t border-slate-200 bg-white px-4 py-6">
      <LegalLinks />
    </footer>
  </div>
</template>

<script setup>
import {
  ArrowPathIcon,
  ArrowRightIcon,
  CloudArrowUpIcon,
  DocumentCheckIcon,
  FingerPrintIcon,
} from '@heroicons/vue/24/outline'
import LegalLinks from '@/components/legal/LegalLinks.vue'
import heroImage from '@/assets/landing/webhdp-hero.jpg'

const metrics = [
  { value: '3D', label: 'Asset-aware workflows' },
  { value: 'EDM', label: 'Standards-oriented output' },
  { value: 'IIIF', label: 'Presentation-ready manifests' },
  { value: 'METS', label: 'Structured package metadata' },
]

const workflowHighlights = [
  {
    title: 'Upload and scan complex datasets',
    description: 'Create resumable sessions for 3D assets, sidecars, metadata spreadsheets, and batch-oriented project files.',
    icon: CloudArrowUpIcon,
  },
  {
    title: 'Validate publication outputs',
    description: 'Generate and check EDM, IIIF, and METS outputs before records move into publishing workflows.',
    icon: DocumentCheckIcon,
  },
  {
    title: 'Publish and retrieve Zenodo records',
    description: 'Prepare Zenodo-ready records, manage publishing contexts, and explore retrieved account records in local HDPC shards.',
    icon: ArrowPathIcon,
  },
  {
    title: 'Preserve process provenance',
    description: 'Keep session-level history, record lineage, and processing state visible across upload, review, and publication steps.',
    icon: FingerPrintIcon,
  },
]
</script>
