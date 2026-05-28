<template>
  <LegalPageLayout eyebrow="Data protection" title="Privacy Policy">
    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Controller</h2>
      <p class="text-sm leading-6 text-gray-700">
        The controller for WebHDP is {{ legalConfig.providerName }}, {{ legalConfig.providerAddressLines.join(', ') }},
        represented by {{ legalConfig.providerRepresentative }}. The project contact is
        {{ legalConfig.projectContactName }}, {{ legalConfig.projectContactAddressLines.join(', ') }}.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        The {{ legalConfig.dataProtectionOfficerLabel }} can be reached at
        <a :href="`mailto:${legalConfig.dataProtectionOfficerEmail}`" class="font-medium text-indigo-700 hover:text-indigo-900">
          {{ legalConfig.dataProtectionOfficerEmail }}
        </a>.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">GDPR Compliance</h2>
      <p class="text-sm leading-6 text-gray-700">
        WebHDP is designed and operated as a fully GDPR-compliant research data application. Personal data is processed
        only where necessary for authentication, account administration, auditability, notifications, data publication
        workflows, security, and the operation of user-requested services.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Processing is based on the performance of public-interest university tasks, legitimate operational interests,
        contractual or pre-contractual user relationships where applicable, legal obligations, and consent where a
        specific optional feature requires it.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Data Processed by WebHDP</h2>
      <ul class="list-disc space-y-2 pl-5 text-sm leading-6 text-gray-700">
        <li>Account data such as email address, role, institution memberships, and verification status.</li>
        <li>Authentication and security data such as session tokens, access logs, rate-limit events, and audit records.</li>
        <li>Research workflow data such as uploaded files, metadata spreadsheets, generated records, provenance, and validation results.</li>
        <li>Publication credentials such as Zenodo API keys, stored encrypted at rest and shown only as masked previews.</li>
        <li>Operational notifications and issue reports submitted by users.</li>
      </ul>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Zenodo Publication and Retrieval</h2>
      <p class="text-sm leading-6 text-gray-700">
        Zenodo is the baseline external service used by WebHDP for publication, draft upload, record management, and
        account retrieval workflows requested by users. Data transferred to Zenodo is limited to the files, metadata,
        credentials, and publication actions required for the selected workflow.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Dropbox, Google Drive, HPC-Link, SMTP mail services, and the local EDM validator are optional deployment
        integrations. They are used only when configured by the operator or selected by the user workflow.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Storage, Retention, and Security</h2>
      <p class="text-sm leading-6 text-gray-700">
        WebHDP stores workflow artifacts, generated records, logs, and operational backups only for as long as needed
        for the configured research, publication, audit, backup, and maintenance purposes. Credential values are
        encrypted at rest. Access to non-public workflow data requires authentication and role-appropriate permissions.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        Early deployed versions of WebHDP are alpha versions and may change during controlled research use. Alpha status
        does not weaken the privacy, security, or GDPR-compliance requirements of the service.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Your Rights</h2>
      <p class="text-sm leading-6 text-gray-700">
        Under the GDPR you may have rights of access, rectification, erasure, restriction of processing, data
        portability, objection, and withdrawal of consent where processing is based on consent. You may contact the
        {{ legalConfig.dataProtectionOfficerLabel }} to exercise these rights.
      </p>
      <p class="text-sm leading-6 text-gray-700">
        You also have the right to lodge a complaint with {{ legalConfig.complaintAuthorityName }}:
        {{ legalConfig.complaintAuthorityAddressLines.join(', ') }}.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-lg font-semibold text-gray-950">Cookies and Browser Storage</h2>
      <p class="text-sm leading-6 text-gray-700">
        WebHDP does not use non-essential tracking cookies by default. Necessary browser storage is described in the
        <router-link to="/cookies" class="font-medium text-indigo-700 hover:text-indigo-900">Cookies and Storage Notice</router-link>.
      </p>
    </section>
  </LegalPageLayout>
</template>

<script setup>
import { legalConfig } from '@/config/legal'
import LegalPageLayout from '@/views/legal/LegalPageLayout.vue'
</script>
