<template>
  <section
    v-if="reservations.length || (error && hadReservations) || (selectSession && (loading || error))"
    class="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4"
    aria-label="Reserved GPUs"
    data-testid="reserved-gpu-access"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 class="text-sm font-semibold text-slate-900">Reserved GPUs</h3>
      <button type="button" class="text-xs font-medium text-indigo-700 underline disabled:opacity-50" :disabled="loading || Boolean(pendingAction)" @click="loadReservations">
        {{ loading ? 'Refreshing…' : 'Refresh' }}
      </button>
    </div>

    <template v-if="selectSession && reservations.length">
      <label class="block text-sm font-medium text-slate-700">
        Uploaded session
        <select
          v-model="selectedSessionId"
          class="mt-1 block w-full rounded-lg border-slate-300 bg-white text-sm"
          :disabled="loadingSessions || Boolean(pendingAction)"
          data-testid="reserved-gpu-session"
        >
          <option value="">{{ loadingSessions ? 'Loading sessions…' : 'Choose a session' }}</option>
          <option v-for="session in sessions" :key="session.id" :value="String(session.id)">
            {{ session.name || session.title || `Session ${session.id}` }}
          </option>
        </select>
      </label>
      <p v-if="!loadingSessions && !sessions.length" class="text-xs text-slate-600">
        <RouterLink to="/workflow/upload" class="font-medium text-indigo-700 underline">Upload files</RouterLink>
        to create a session for GPU processing.
      </p>
    </template>

    <article
      v-for="reservation in reservations"
      :key="reservation.reservation_id"
      :data-testid="`reserved-gpu-card-${reservation.reservation_id}`"
      class="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-sm"
    >
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="min-w-0 break-words font-medium text-slate-900">{{ reservation.label }}</p>
        <span
          class="rounded-full px-2 py-0.5 text-xs font-medium"
          :class="isAvailable(reservation) ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-700'"
        >
          {{ isExpired(reservation) ? 'Expired' : reservationStatusLabel(reservation.status) }}
        </span>
      </div>
      <p v-if="reservationHardware(reservation)" class="text-xs text-slate-700">{{ reservationHardware(reservation) }}</p>
      <p class="text-xs text-slate-600">
        {{ [reservation.node_name, reservation.partition].filter(Boolean).join(' · ') }}
        <template v-if="reservationExpiry(reservation.expires_at, now)">
          <span v-if="reservation.node_name || reservation.partition"> · </span>
          <time :datetime="reservation.expires_at" :title="new Date(reservation.expires_at).toLocaleString()">
            {{ reservationExpiry(reservation.expires_at, now).label }}
          </time>
        </template>
      </p>
      <div v-if="reservation.allocation" class="space-y-2">
        <p class="text-xs font-medium text-indigo-900">
          {{ allocationStatus(reservation) }}
        </p>
        <button
          v-if="canRetry(reservation)"
          type="button"
          class="mr-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          :disabled="disabled || Boolean(pendingAction)"
          @click="claimReservation(reservation)"
        >
          {{ pendingAction === `claim:${reservation.reservation_id}` ? 'Connecting…' : 'Retry connection' }}
        </button>
        <button
          type="button"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          :disabled="disabled || Boolean(pendingAction) || reservation.allocation.can_release === false"
          @click="releaseReservation(reservation)"
        >
          {{ pendingAction === `release:${reservation.reservation_id}` ? 'Releasing…' : 'Release access' }}
        </button>
      </div>
      <button
        v-else-if="isAvailable(reservation)"
        type="button"
        class="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        :disabled="disabled || !targetSessionId || Boolean(pendingAction)"
        @click="claimReservation(reservation)"
      >
        {{ pendingAction === `claim:${reservation.reservation_id}` ? 'Connecting…' : 'Use reserved GPU' }}
      </button>
    </article>
    <p v-if="error" class="text-sm text-rose-700" role="alert">{{ error }}</p>
    <p v-if="message" role="status" class="text-sm text-emerald-800">{{ message }}</p>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import fileService from '@/services/file.service'
import hpcLinkService from '@/services/hpcLink.service'
import { useAuthStore } from '@/stores/auth'
import { reservationExpiry, reservationHardware, reservationStatusLabel } from '@/utils/hpcReservation'

const props = defineProps({
  sessionId: { type: [String, Number], default: '' },
  purpose: { type: String, default: 'workflow' },
  selectSession: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const auth = props.selectSession ? useAuthStore() : null
const emit = defineEmits(['claimed', 'released', 'session-allocation'])
const reservations = ref([])
const hadReservations = ref(false)
const selectedSessionId = ref('')
const sessions = ref([])
const loading = ref(false)
const loadingSessions = ref(false)
const pendingAction = ref('')
const error = ref('')
const message = ref('')
const now = ref(Date.now())
let timer

const targetSessionId = computed(() => {
  const id = Number(props.selectSession ? selectedSessionId.value : props.sessionId)
  return Number.isSafeInteger(id) && id > 0 ? id : null
})

const isExpired = (reservation) => reservationExpiry(reservation.expires_at, now.value)?.expired === true
const isAvailable = (reservation) => reservation.status === 'available' && reservation.can_claim === true && !isExpired(reservation)
const isCurrentSession = (allocation) => targetSessionId.value !== null && Number(allocation.session_id) === targetSessionId.value
const canRetry = (reservation) => Boolean(reservation.allocation && isCurrentSession(reservation.allocation)
  && reservation.allocation.status === 'allocating' && reservation.enabled !== false && !isExpired(reservation))
const errorMessage = (failure, fallback) => failure?.error?.message || failure?.message || fallback

function allocationStatus(reservation) {
  const allocation = reservation.allocation
  if (isExpired(reservation) || reservation.status === 'expired') return 'The GPU reservation has ended.'
  if (!isCurrentSession(allocation)) return `In use by your session ${allocation.session_id}`
  if (allocation.status === 'allocating') return allocation.last_error || 'Waiting for HPC-Link to confirm this session.'
  if (reservation.status === 'in_use' && allocation.status === 'running') return 'Ready for this session'
  return 'Access is assigned to this session.'
}

async function loadSessions() {
  if (loadingSessions.value) return
  loadingSessions.value = true
  try {
    const response = await fileService.listSessions()
    sessions.value = (response.data?.sessions || []).filter(session => Number(session.owner_user_id) === Number(auth?.user?.id))
  } catch (failure) {
    error.value = errorMessage(failure, 'Could not load uploaded sessions.')
  } finally {
    loadingSessions.value = false
  }
}

async function loadReservations() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await hpcLinkService.listReservations(props.purpose)
    reservations.value = response.data?.reservations || []
    if (reservations.value.length) hadReservations.value = true
    now.value = Date.now()
    if (props.selectSession && reservations.value.length) await loadSessions()
  } catch (failure) {
    reservations.value = []
    error.value = errorMessage(failure, 'Could not check reserved GPUs.')
  } finally {
    loading.value = false
  }
}

async function claimReservation(reservation) {
  if (props.disabled || !targetSessionId.value || pendingAction.value || (!isAvailable(reservation) && !canRetry(reservation))) return
  pendingAction.value = `claim:${reservation.reservation_id}`
  message.value = ''
  error.value = ''
  const sessionId = targetSessionId.value
  try {
    const response = await hpcLinkService.claimReservation(reservation.reservation_id, {
      purpose: props.purpose,
      session_id: sessionId,
    })
    const allocation = response.data?.allocation
    if (allocation?.status === 'running') {
      message.value = `Reserved GPU ready for session ${sessionId}.`
      emit('claimed', allocation)
    }
    await loadReservations()
  } catch (failure) {
    await loadReservations()
    error.value = errorMessage(failure, 'Could not use this reservation.')
  } finally {
    pendingAction.value = ''
  }
}

async function releaseReservation(reservation) {
  const allocation = reservation.allocation
  if (props.disabled || pendingAction.value || !allocation?.allocation_id || allocation.can_release === false) return
  pendingAction.value = `release:${reservation.reservation_id}`
  message.value = ''
  error.value = ''
  try {
    await hpcLinkService.releaseAllocation(allocation.allocation_id)
    message.value = 'Access released. The Slurm reservation keeps its scheduled end time.'
    emit('released', allocation)
    await loadReservations()
  } catch (failure) {
    await loadReservations()
    error.value = errorMessage(failure, 'Could not release access to this GPU.')
  } finally {
    pendingAction.value = ''
  }
}

watch(targetSessionId, () => { message.value = '' })
const currentAllocation = computed(() => reservations.value.find(reservation => (
  reservation.allocation && isCurrentSession(reservation.allocation) && !isExpired(reservation)
))?.allocation ?? null)
watch(currentAllocation, allocation => emit('session-allocation', allocation))

onMounted(() => {
  loadReservations()
  timer = window.setInterval(() => { now.value = Date.now() }, 15000)
})
onUnmounted(() => window.clearInterval(timer))
</script>
