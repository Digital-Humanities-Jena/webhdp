<template>
  <LegalPageLayout eyebrow="Browser storage" title="Cookies and Storage Notice">
    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">No Non-Essential Tracking Cookies</h2>
      <p class="text-sm leading-6 text-gray-700">
        WebHDP does not set non-essential tracking cookies by default. The application uses only necessary browser
        storage and server-side session mechanisms required to provide a secure, reliable research workflow.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Necessary Browser Storage</h2>
      <ul class="list-disc space-y-2 pl-5 text-sm leading-6 text-gray-700">
        <li>Authentication tokens in session storage, used to keep signed-in users authenticated during the browser session.</li>
        <li>Workflow state in session storage, used to resume upload and metadata steps without losing progress.</li>
        <li>Issue draft context in session storage, used to prefill report metadata when a user opens the issue form.</li>
        <li>Directory upload recovery state in session storage, used to resume interrupted upload submissions.</li>
        <li>A local storage flag recording that this cookies and storage notice has been dismissed.</li>
      </ul>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Server-Side Session and Security Data</h2>
      <p class="text-sm leading-6 text-gray-700">
        WebHDP may use server-side session records, JWT verification, access logs, rate-limit records, and audit events
        to secure the service and document user-requested publication workflows. These mechanisms are necessary for the
        operation of a GDPR-compliant authenticated research data platform.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Optional Integrations</h2>
      <p class="text-sm leading-6 text-gray-700">
        Zenodo publication and retrieval are part of the baseline WebHDP workflow. Optional deployment integrations such
        as Dropbox, Google Drive, HPC-Link, SMTP mail, and local EDM validation may involve additional service-specific
        storage or transfer only when configured and used.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Managing Storage</h2>
      <p class="text-sm leading-6 text-gray-700">
        You can clear browser storage through your browser settings. Clearing necessary storage may sign you out,
        dismiss saved workflow recovery state, or cause in-progress forms to lose local draft context.
      </p>
    </section>
  </LegalPageLayout>
</template>

<script setup>
import LegalPageLayout from '@/views/legal/LegalPageLayout.vue'
</script>
