<template>
  <section ref="review" tabindex="-1" aria-label="Selected sample"
    class="rounded-xl border border-slate-200 bg-white p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 sm:p-6">
    <h2 class="text-lg font-semibold">Review metadata</h2>
    <p class="mt-1 text-sm text-slate-600">
      WebHDP matches each model to a row in the included metadata spreadsheet (MSF).
    </p>
    <label v-if="sample.records.length > 1" class="mt-4 block max-w-md text-sm font-semibold">
      Model in this batch
      <select v-model="index" class="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2">
        <option v-for="(row, i) in sample.records" :key="row.filename" :value="i">{{ row.title }}</option>
      </select>
    </label>
    <div class="mt-4 grid gap-3 text-sm sm:grid-cols-2">
      <label class="block font-semibold">Title
        <input :value="row.title" readonly class="review-field" />
      </label>
      <label class="block font-semibold">Creator
        <input :value="row.creator" readonly class="review-field" />
      </label>
      <label class="block font-semibold sm:col-span-2">Description
        <textarea :value="row.description" readonly rows="2" class="review-field" />
      </label>
      <label class="block font-semibold">License
        <input :value="row.license === 'cc0-1.0' ? 'CC0 1.0' : row.license" readonly class="review-field" />
      </label>
      <label class="block font-semibold">Source model
        <input :value="row.filename" readonly class="review-field" />
      </label>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ sample: { type: Object, required: true } })
const index = ref(0)
const review = ref(null)
const row = computed(() => props.sample.records[index.value] || props.sample.records[0])
defineExpose({ focus: () => review.value?.focus({ preventScroll: true }), scrollIntoView: options => review.value?.scrollIntoView(options) })
</script>

<style scoped>
.review-field {
  @apply mt-1 block w-full min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-normal text-slate-800;
}
</style>
