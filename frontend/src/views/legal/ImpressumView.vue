<template>
  <LegalPageLayout eyebrow="Legal notice" title="Impressum">
    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Provider</h2>
      <p class="text-sm leading-6 text-gray-700">
        {{ legalConfig.providerName }}<br>
        <template v-for="line in legalConfig.providerAddressLines" :key="line">
          {{ line }}<br>
        </template>
      </p>
      <p class="text-sm leading-6 text-gray-700">
        {{ legalConfig.providerName }} is legally represented by {{ legalConfig.providerRepresentative }}.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Supervisory Authority</h2>
      <p class="text-sm leading-6 text-gray-700">
        {{ legalConfig.supervisoryAuthorityName }}<br>
        <template v-for="line in legalConfig.supervisoryAuthorityAddressLines" :key="line">
          {{ line }}<br>
        </template>
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">VAT Identification Number</h2>
      <p class="text-sm leading-6 text-gray-700">{{ legalConfig.vatId }}</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Project and Editorial Contact</h2>
      <p class="text-sm leading-6 text-gray-700">
        {{ legalConfig.projectContactName }}<br>
        <template v-for="line in legalConfig.projectContactAddressLines" :key="line">
          {{ line }}<br>
        </template>
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Email:
        <a :href="`mailto:${legalConfig.projectContactEmail}`" class="font-medium text-indigo-700 hover:text-indigo-900">
          {{ legalConfig.projectContactEmail }}
        </a>
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Funding and Project Context</h2>
      <p class="text-sm leading-6 text-gray-700">
        The development of WebHDP was part of 3DBigDataSpace, officially described as
        "3D Big Data for the Data Space for Cultural Heritage", funded by the European Union under Grant Agreement
        No. 101173385. Development will continue as part of INFINITY, officially titled "Multidimensional
        knowledge-based annotation for ethical context-aware heritage data life cycles", funded by the European
        Commission under Grant Agreement No. 101233051.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Views and opinions expressed in WebHDP are those of the author(s) only and do not necessarily reflect those of
        the European Union, HADEA, or the granting authority. Neither the European Union nor the granting authority can
        be held responsible for them.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Developer credits, contributor affiliations, and project source links are listed on the
        <router-link to="/credits" class="font-medium text-indigo-700 hover:text-indigo-900">
          WebHDP credits page
        </router-link><span>.</span>
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Alpha Versions</h2>
      <p class="text-sm leading-6 text-gray-700">
        Early deployed WebHDP versions are alpha versions. They are intended for controlled research and operational
        testing, may change without notice, and may contain incomplete functionality. This alpha status does not reduce
        WebHDP's commitment to secure operation and full GDPR compliance.
      </p>
    </section>
  </LegalPageLayout>
</template>

<script setup>
import { legalConfig } from '@/config/legal'
import LegalPageLayout from '@/views/legal/LegalPageLayout.vue'
</script>
