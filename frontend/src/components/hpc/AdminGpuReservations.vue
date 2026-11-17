<template>
  <section class="space-y-5 p-6" aria-label="Manage reserved GPUs">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-slate-900">Reserved GPUs</h2>
        <p class="mt-1 max-w-2xl text-sm text-slate-600">
          Register the running Slurm job in HPC-Link, then paste the gateway reservation ID here. Add the existing WebHDP accounts that can use the GPU.
        </p>
        <p class="mt-1 text-xs text-slate-600">Allowed accounts also need HPC access. One session can use the reservation at a time.</p>
      </div>
      <button type="button" class="rounded-md border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50" :disabled="loading || saving" @click="loadReservations">
        {{ loading ? 'Refreshing…' : 'Refresh' }}
      </button>
    </div>

    <form class="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4" data-testid="admin-gpu-reservation-form" @submit.prevent="saveReservation">
      <h3 class="text-sm font-semibold text-slate-900">{{ editingId ? 'Edit reservation access' : 'Register a reservation' }}</h3>
      <div class="grid gap-4 sm:grid-cols-2">
        <label v-if="!editingId" class="block text-sm font-medium text-slate-700">
          Gateway reservation ID
          <input v-model.trim="form.gatewayId" required type="text" class="mt-1 block w-full rounded-md border-slate-300 text-sm" autocomplete="off" />
        </label>
        <label class="block text-sm font-medium text-slate-700">
          Display name
          <input v-model.trim="form.label" required maxlength="120" type="text" class="mt-1 block w-full rounded-md border-slate-300 text-sm" placeholder="Live presentation GPU" />
        </label>
      </div>
      <label class="block text-sm font-medium text-slate-700">
        Allowed account emails
        <textarea
          v-model="form.emails"
          required
          rows="3"
          class="mt-1 block w-full rounded-md border-slate-300 text-sm"
          placeholder="presenter@example.org"
          aria-describedby="gpu-allowed-emails-help"
        />
      </label>
      <p id="gpu-allowed-emails-help" class="text-xs text-slate-600">Separate addresses with a comma or put one on each line.</p>
      <div class="flex gap-3">
        <button type="submit" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50" :disabled="saving || !canSave">
          {{ saving ? 'Saving…' : editingId ? 'Save access' : 'Register GPU' }}
        </button>
        <button v-if="editingId" type="button" class="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-50" :disabled="saving" @click="resetForm">Cancel edit</button>
      </div>
    </form>

    <p v-if="error" role="alert" class="text-sm text-rose-700">{{ error }}</p>
    <p v-if="message" role="status" class="text-sm text-emerald-800">{{ message }}</p>
    <p v-if="!loading && !reservations.length && !error" class="text-sm text-slate-600">No GPU reservations have been registered.</p>
    <div v-if="reservations.length" class="grid gap-3 lg:grid-cols-2">
      <article v-for="reservation in reservations" :key="reservation.reservation_id" class="space-y-2 rounded-lg border border-slate-200 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="break-words text-sm font-semibold text-slate-900">{{ reservation.label }}</h3>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{{ reservationStatusLabel(reservation.status) }}</span>
        </div>
        <p class="text-sm text-slate-700">
          <span v-if="reservation.job_id">Slurm job {{ reservation.job_id }}</span>
          <span v-if="reservation.node_name"> · {{ reservation.node_name }}</span>
          <span v-if="reservation.partition"> · {{ reservation.partition }}</span>
        </p>
        <p v-if="reservationHardware(reservation)" class="text-xs text-slate-600">{{ reservationHardware(reservation) }}</p>
        <p v-if="reservation.expires_at" class="text-xs text-slate-600">
          Ends <time :datetime="reservation.expires_at">{{ new Date(reservation.expires_at).toLocaleString() }}</time>
        </p>
        <p class="break-words text-xs text-slate-600">Allowed accounts: {{ (reservation.allowed_emails || []).join(', ') || 'None' }}</p>
        <div class="flex flex-wrap gap-2 pt-1">
          <button type="button" class="rounded-md border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50" :disabled="saving" @click="editReservation(reservation)">Edit access</button>
          <button
            type="button"
            class="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            :disabled="saving || reservation.status === 'in_use' || reservation.status === 'expired'"
            @click="toggleReservation(reservation)"
          >
            {{ reservation.enabled === false ? 'Enable access' : 'Disable access' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import adminService from '@/services/admin.service'
import { reservationHardware, reservationStatusLabel } from '@/utils/hpcReservation'

const reservations = ref([])
const loading = ref(false)
const saving = ref(false)
const editingId = ref('')
const error = ref('')
const message = ref('')
const form = reactive({ gatewayId: '', label: '', emails: '' })
const allowedEmails = computed(() => [...new Set(form.emails.split(/[,\s;]+/).filter(Boolean).map((email) => email.toLowerCase()))])
const canSave = computed(() => Boolean(form.label && allowedEmails.value.length && (editingId.value || form.gatewayId)))

const errorMessage = (failure, fallback) => failure?.error?.message || failure?.message || fallback

async function loadReservations() {
  loading.value = true
  error.value = ''
  try {
    const response = await adminService.listHpcReservations()
    reservations.value = response.data?.reservations || []
  } catch (failure) {
    error.value = errorMessage(failure, 'Could not check registered GPU reservations.')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editingId.value = ''
  Object.assign(form, { gatewayId: '', label: '', emails: '' })
}

function editReservation(reservation) {
  editingId.value = reservation.reservation_id
  error.value = ''
  message.value = ''
  Object.assign(form, { gatewayId: '', label: reservation.label, emails: (reservation.allowed_emails || []).join('\n') })
}

async function saveReservation() {
  if (saving.value || !canSave.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  const payload = { label: form.label, allowed_emails: allowedEmails.value }
  try {
    if (editingId.value) {
      await adminService.updateHpcReservation(editingId.value, payload)
      message.value = 'Reservation access updated.'
    } else {
      await adminService.registerHpcReservation({ ...payload, gateway_reservation_id: form.gatewayId })
      message.value = 'GPU reservation registered.'
    }
    resetForm()
    await loadReservations()
  } catch (failure) {
    error.value = errorMessage(failure, 'Could not save this GPU reservation.')
  } finally {
    saving.value = false
  }
}

async function toggleReservation(reservation) {
  if (saving.value || reservation.status === 'in_use' || reservation.status === 'expired') return
  saving.value = true
  error.value = ''
  message.value = ''
  const enabled = reservation.enabled === false
  try {
    await adminService.updateHpcReservation(reservation.reservation_id, { enabled })
    message.value = enabled ? 'WebHDP access enabled.' : 'WebHDP access disabled. Slurm keeps the reservation.'
    await loadReservations()
  } catch (failure) {
    error.value = errorMessage(failure, 'Could not update reservation access.')
  } finally {
    saving.value = false
  }
}

onMounted(loadReservations)
</script>
