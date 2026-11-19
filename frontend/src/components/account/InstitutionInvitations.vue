<template>
  <div class="space-y-4 border-b border-gray-200 pb-5">
    <div>
      <h3 class="font-semibold text-gray-900">Invite someone</h3>
      <p class="mt-1 text-sm text-gray-600">They can join after verifying their email and accepting the invitation.</p>
    </div>
    <form class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-end" @submit.prevent="send(email, role)">
      <label class="min-w-0 text-sm font-medium text-gray-900">
        Email address
        <input v-model.trim="email" required maxlength="254" type="text" inputmode="email" autocomplete="off" autocapitalize="none" :spellcheck="false"
          class="mt-1 block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500" />
      </label>
      <label class="text-sm font-medium text-gray-900">
        Role
        <select v-model="role" class="mt-1 block w-full rounded-md border-gray-300 text-sm capitalize focus:border-indigo-500 focus:ring-indigo-500">
          <option v-for="option in roles" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <button type="submit" :disabled="Boolean(working)" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
        Send invitation
      </button>
    </form>

    <p v-if="notice" role="status" class="text-sm text-gray-800">{{ notice }}</p>
    <p v-if="error" role="alert" class="text-sm text-red-800">{{ error }}</p>

    <div class="flex items-center justify-between gap-3">
      <h3 class="font-semibold text-gray-900">Invitations</h3>
      <button type="button" :disabled="loading || Boolean(working)" class="text-sm font-medium text-indigo-700 underline disabled:opacity-50" @click="load(0)">
        Refresh invitations
      </button>
    </div>
    <p v-if="loading" role="status" class="text-sm text-gray-600">Checking invitations…</p>
    <p v-else-if="!invitations.length" class="text-sm text-gray-600">No invitations to show.</p>
    <ul v-else class="divide-y divide-gray-200">
      <li v-for="invitation in invitations" :key="invitation.id" class="flex flex-wrap items-center justify-between gap-2 py-2">
        <div class="min-w-0">
          <p class="break-all text-sm font-medium text-gray-900">{{ invitation.email }}</p>
          <p class="text-xs capitalize text-gray-600">{{ invitation.role }} · {{ invitation.status }}</p>
        </div>
        <div class="flex flex-wrap gap-3">
          <button v-if="roles.includes(invitation.role) && ['pending', 'expired'].includes(invitation.status)" type="button"
            :disabled="Boolean(working)" class="text-sm font-medium text-indigo-700 underline disabled:opacity-50"
            :aria-label="`Resend invitation to ${invitation.email}`" @click="send(invitation.email, invitation.role, invitation.id)">
            Resend
          </button>
          <button v-if="roles.includes(invitation.role) && invitation.status === 'pending'" type="button"
            :disabled="Boolean(working)" class="text-sm font-medium text-red-800 underline disabled:opacity-50"
            :aria-label="`Revoke invitation to ${invitation.email}`" @click="revoke(invitation)">
            Revoke
          </button>
        </div>
      </li>
    </ul>
    <div v-if="total > pageSize" class="flex flex-wrap items-center gap-4 text-sm text-gray-700">
      <button type="button" :disabled="loading || offset === 0" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="load(offset - pageSize)">Previous</button>
      <span>{{ offset + 1 }}–{{ Math.min(offset + pageSize, total) }} of {{ total }}</span>
      <button type="button" :disabled="loading || offset + pageSize >= total" class="font-medium text-indigo-700 underline disabled:opacity-50" @click="load(offset + pageSize)">Next</button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import institutionService from '@/services/institution.service'
import { identityActionError } from '@/utils/emailAction'

const props = defineProps({
  institutionId: { type: Number, required: true },
  roles: { type: Array, required: true },
})
const emit = defineEmits(['changed'])
const email = ref('')
const role = ref('reader')
const invitations = ref([])
const loading = ref(false)
const working = ref('')
const notice = ref('')
const error = ref('')
const offset = ref(0)
const total = ref(0)
const pageSize = 10

async function load(start = offset.value) {
  loading.value = true
  try {
    const response = await institutionService.listInvitations(props.institutionId, { limit: pageSize, offset: start })
    invitations.value = response.data?.invitations || []
    offset.value = start
    total.value = response.data?.total ?? invitations.value.length
  } catch (err) {
    error.value = identityActionError(err, 'Could not load invitations. Refresh to try again.')
  } finally {
    loading.value = false
  }
}

async function send(address, invitationRole, id) {
  if (working.value) return
  working.value = id || 'new'
  error.value = ''
  notice.value = ''
  try {
    const response = await institutionService.sendInvitation(props.institutionId, { email: address, role: invitationRole })
    if (response.data?.delivery === 'failed') {
      error.value = 'The invitation was saved, but the email could not be sent. Use Resend to try again.'
    } else {
      notice.value = 'Invitation email sent.'
    }
    if (!id) {
      email.value = ''
      role.value = 'reader'
    }
    await load(0)
    emit('changed')
  } catch (err) {
    error.value = identityActionError(err, 'Could not send the invitation. Try again shortly.')
  } finally {
    working.value = ''
  }
}

async function revoke(invitation) {
  if (working.value) return
  working.value = invitation.id
  error.value = ''
  notice.value = ''
  try {
    await institutionService.revokeInvitation(props.institutionId, invitation.id)
    notice.value = 'Invitation revoked.'
    await load()
    emit('changed')
  } catch (err) {
    error.value = identityActionError(err, 'Could not revoke this invitation.')
  } finally {
    working.value = ''
  }
}

onMounted(load)
</script>
