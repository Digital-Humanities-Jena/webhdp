<template>
  <section class="max-w-3xl mx-auto p-6 space-y-4">
    <h1 class="text-2xl font-semibold text-gray-900">Login security</h1>
    <p class="text-gray-600">Users sign in with their email and password. Each user can enable or disable email two-factor authentication in Account Configuration.</p>
    <p class="text-gray-600">Enabling two-factor authentication requires a working email delivery service and a successful confirmation code. Provider-wide bypass rules no longer apply.</p>
    <router-link to="/account/configuration" class="inline-flex rounded-md bg-indigo-600 px-4 py-2 text-white">Open account configuration</router-link>
  </section>
</template>
