<template>
  <section aria-labelledby="model-queue-heading" class="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
    <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 id="model-queue-heading" class="text-sm font-semibold text-slate-900">Processing queue</h2>
      <p v-if="queue && !unavailable" class="text-sm tabular-nums text-slate-700" aria-label="Current queue counts">
        <span class="font-semibold">{{ queue.queued }}</span> waiting
        <span class="px-1 text-slate-400" aria-hidden="true">·</span>
        <span class="font-semibold">{{ queue.running }}</span> running
        <span v-if="queue.capacity > 0" class="text-slate-600"> ({{ queue.capacity }} slots)</span>
      </p>
    </div>
    <div class="mt-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-slate-700">
      <p v-if="personStatus" :aria-live="canOpenJob ? 'polite' : 'off'">{{ personStatus }}</p>
      <p v-if="offline" role="status" class="text-amber-900">Processing is temporarily unavailable.</p>
      <p v-else-if="unavailable" role="status" class="text-amber-900">Queue status unavailable. WebHDP will check again.</p>
      <p v-else-if="!queue && !personStatus" role="status">Checking worker availability…</p>
      <p v-else-if="!personStatus">Requests start automatically as slots become free.</p>
      <p v-if="expiration" class="text-xs text-slate-600">
        Demo access ends at <time :datetime="expiration.toISOString()">{{ timeLabel }}</time>
      </p>
      <button v-if="canOpenJob" type="button" class="font-semibold text-indigo-700 underline underline-offset-4" @click="$emit('open-job')">
        View your request
      </button>
      <button v-else-if="unavailable || offline" type="button" class="font-semibold text-indigo-700 underline underline-offset-4" @click="$emit('refresh')">
        Refresh queue
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  queue: { type: Object, default: null },
  job: { type: Object, default: null },
  unavailable: { type: Boolean, default: false },
  offline: { type: Boolean, default: false },
  canOpenJob: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
  uploadPercent: { type: Number, default: null },
  expiresAt: { type: Number, default: null }
})
defineEmits(['open-job', 'refresh'])

const expiration = computed(() => {
  if (!Number.isFinite(props.expiresAt) || props.expiresAt <= 0) return null
  const deadline = new Date(props.expiresAt * 1000)
  return Number.isNaN(deadline.getTime()) ? null : deadline
})
const timeLabel = computed(() => expiration.value?.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }))

const personStatus = computed(() => {
  if (props.submitting) {
    return props.uploadPercent === null ? 'Sending your request…' : `Uploading your model · ${props.uploadPercent}%`
  }
  const job = props.job
  if (job?.status === 'queued') {
    if (job.ahead === 0) return 'Your request is next.'
    const position = job.position ?? (Number.isInteger(job.ahead) ? job.ahead + 1 : null)
    return position ? `Your place in the queue is ${position}.` : 'Your request is waiting for a free slot.'
  }
  if (job?.status === 'running') return 'Your request is processing.'
  return ''
})
</script>
