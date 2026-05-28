<template>
  <div class="min-h-screen bg-slate-50 text-slate-950">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <router-link to="/" class="text-lg font-semibold tracking-tight text-slate-950">WebHDP</router-link>
        <LegalLinks />
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <section class="max-w-3xl">
        <p class="text-xs font-semibold uppercase tracking-wide text-teal-700">People and project context</p>
        <h1 class="mt-3 text-4xl font-bold tracking-normal text-slate-950 sm:text-5xl">
          Credits
        </h1>
        <p class="mt-4 text-base leading-7 text-slate-600">
          WebHDP is developed in a research context shaped by Digital Humanities, organology, and European cultural heritage infrastructure projects.
        </p>
      </section>

      <section class="mt-10 grid gap-4 lg:grid-cols-[1.05fr,0.95fr]">
        <article class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div class="flex items-start gap-4">
            <span class="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-teal-50 text-teal-700 ring-1 ring-teal-100">
              <UserCircleIcon class="h-7 w-7" aria-hidden="true" />
            </span>
            <div>
              <p class="text-sm font-semibold uppercase tracking-wide text-slate-500">{{ credits.leadDeveloper.role }}</p>
              <h2 class="mt-2 text-2xl font-bold tracking-normal text-slate-950">{{ credits.leadDeveloper.name }}</h2>
              <ul class="mt-4 space-y-2">
                <li
                  v-for="affiliation in credits.leadDeveloper.affiliations"
                  :key="affiliation.text"
                  class="text-sm leading-6 text-slate-700"
                  :class="{ italic: affiliation.emphasis }"
                >
                  {{ affiliation.text }}
                </li>
              </ul>
              <div class="mt-5 flex flex-wrap gap-3 text-sm">
                <a
                  :href="`mailto:${credits.leadDeveloper.email}`"
                  class="font-medium text-teal-700 hover:text-teal-900"
                >
                  {{ credits.leadDeveloper.email }}
                </a>
                <a
                  :href="credits.leadDeveloper.orcidUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-teal-700 hover:text-teal-900"
                >
                  ORCID {{ credits.leadDeveloper.orcid }}
                </a>
              </div>
            </div>
          </div>
        </article>

        <article class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div class="flex items-start gap-4">
            <span class="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700 ring-1 ring-amber-100">
              <UserGroupIcon class="h-7 w-7" aria-hidden="true" />
            </span>
            <div class="min-w-0">
              <h2 class="text-2xl font-bold tracking-normal text-slate-950">Contributing developers</h2>
              <div v-if="credits.contributors.length" class="mt-4 space-y-4">
                <div v-for="contributor in credits.contributors" :key="contributor.name">
                  <p class="text-sm font-semibold text-slate-950">{{ contributor.name }}</p>
                  <p v-if="contributor.affiliation" class="mt-1 text-sm leading-6 text-slate-600">
                    {{ contributor.affiliation }}
                  </p>
                </div>
              </div>
              <p v-else class="mt-4 text-sm leading-6 text-slate-600">
                Additional contributing developers can be added by editing the credits data file.
              </p>
            </div>
          </div>
        </article>
      </section>

      <section class="mt-10">
        <div class="max-w-3xl">
          <h2 class="text-2xl font-bold tracking-normal text-slate-950">EU project context</h2>
          <p class="mt-3 text-sm leading-6 text-slate-600">
            WebHDP's project attribution follows the funding language used by the related EU project sources.
          </p>
        </div>

        <div class="mt-6 grid gap-4 lg:grid-cols-2">
          <article
            v-for="project in credits.projects"
            :key="project.id"
            class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 class="text-xl font-bold tracking-normal text-slate-950">{{ project.name }}</h3>
                <p v-if="project.officialName" class="mt-1 text-sm font-medium leading-6 text-slate-700">
                  {{ project.officialName }}
                </p>
                <p class="mt-2 text-sm leading-6 text-slate-600">{{ project.relationship }}</p>
              </div>
              <a
                :href="project.url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-50"
              >
                Source
                <ArrowTopRightOnSquareIcon class="ml-2 h-4 w-4" aria-hidden="true" />
              </a>
            </div>

            <dl class="mt-5 grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt class="font-semibold text-slate-500">Grant Agreement</dt>
                <dd class="mt-1 font-semibold text-slate-950">No. {{ project.grantAgreement }}</dd>
              </div>
              <div>
                <dt class="font-semibold text-slate-500">Funder</dt>
                <dd class="mt-1 text-slate-950">{{ project.funder }}</dd>
              </div>
              <div v-if="project.programme" class="sm:col-span-2">
                <dt class="font-semibold text-slate-500">Programme</dt>
                <dd class="mt-1 text-slate-950">{{ project.programme }}</dd>
              </div>
            </dl>

            <p class="mt-5 border-t border-slate-200 pt-4 text-xs leading-5 text-slate-500">
              {{ project.disclaimer }}
            </p>
          </article>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import {
  ArrowTopRightOnSquareIcon,
  UserCircleIcon,
  UserGroupIcon,
} from '@heroicons/vue/24/outline'
import LegalLinks from '@/components/legal/LegalLinks.vue'
import credits from '@/content/credits.json'
</script>
