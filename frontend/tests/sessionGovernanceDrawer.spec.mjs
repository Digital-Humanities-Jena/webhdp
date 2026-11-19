import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  fileService: {
    getSessionWorkspace: vi.fn(),
    getSessionAuditEvents: vi.fn(),
    updateSessionWorkspace: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import SessionGovernanceDrawer from '../src/components/dashboard/SessionGovernanceDrawer.vue'

function buildWorkspaceDetails({
  canManage = true,
  currentWorkspace = {},
  previewInstitutionId = null,
  targetInstitutions = [{ id: 7, name: 'Museum Network', eligible: true }],
  publishingCandidates = [{ id: 1, email: 'owner@example.com', eligible: true, is_current: true }],
} = {}) {
  return {
    data: {
      session: {
        id: 42,
        permissions: {
          can_manage: canManage,
          can_change_visibility: canManage,
        },
        origin_type: currentWorkspace.origin_type || 'workflow',
        access_mode: currentWorkspace.access_mode || 'full',
        workspace: {
          type: currentWorkspace.institution_id ? 'institution' : 'personal',
          institution: currentWorkspace.institution_id ? { id: currentWorkspace.institution_id, name: 'Museum Network' } : null,
        },
        publishing_context: {
          effective_credential_source: currentWorkspace.institution_id ? 'institution' : 'user',
        },
      },
      owner_user: {
        id: 1,
        email: 'owner@example.com',
        full_name: 'Owner User',
      },
      current_publishing_user: {
        id: currentWorkspace.publishing_user_id || 1,
        email: currentWorkspace.publishing_user_id === 2 ? 'manager@example.com' : 'owner@example.com',
      },
      current_workspace: {
        institution_id: currentWorkspace.institution_id || null,
        sharing_scope: currentWorkspace.sharing_scope || 'private',
        credential_preference: currentWorkspace.credential_preference || 'user',
        publishing_user_id: currentWorkspace.publishing_user_id || 1,
        default_zenodo_environment: currentWorkspace.default_zenodo_environment || 'sandbox',
        use_institution_default_communities: Boolean(currentWorkspace.use_institution_default_communities),
      },
      preview_institution_id: previewInstitutionId,
      target_institutions: targetInstitutions,
      publishing_user_candidates: publishingCandidates,
      options: {
        sharing_scopes: [
          { value: 'private', label: 'Private' },
          { value: 'institution', label: 'Institution' },
        ],
        credential_preferences: [
          { value: 'user', label: 'User' },
          { value: 'institution', label: 'Institution' },
        ],
        default_zenodo_environments: [
          { value: 'sandbox', label: 'Sandbox' },
          { value: 'production', label: 'Production' },
        ],
      },
      hdpc_download_policy: {
        scope: 'owner_only',
        can_download: false,
        message: 'Only the session owner can download raw .hdpc files.',
      },
      shared_hdpc_download_policy: {
        scope: 'institution_reader_plus',
        enabled: true,
        can_download: true,
        message: 'Institution readers and above can download the sanitized shared .hdpc export for institution-shared sessions.',
        artifact_kind: 'sanitized_shared',
      },
    },
  }
}

describe('SessionGovernanceDrawer', () => {
  beforeEach(() => {
    Object.values(mocked.fileService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
  })

  it('updates publishing candidates when previewing an institution workspace and saves through the workspace endpoint', async () => {
    mocked.fileService.getSessionWorkspace
      .mockResolvedValueOnce(buildWorkspaceDetails())
      .mockResolvedValueOnce(buildWorkspaceDetails({
        previewInstitutionId: 7,
        publishingCandidates: [
          { id: 2, email: 'manager@example.com', full_name: 'Manager User', institution_role: 'manager', eligible: true, is_current: false },
        ],
      }))
      .mockResolvedValueOnce(buildWorkspaceDetails({
        currentWorkspace: {
          institution_id: 7,
          sharing_scope: 'private',
          credential_preference: 'user',
          publishing_user_id: 2,
          default_zenodo_environment: 'sandbox',
          use_institution_default_communities: false,
        },
        previewInstitutionId: 7,
        publishingCandidates: [
          { id: 2, email: 'manager@example.com', full_name: 'Manager User', institution_role: 'manager', eligible: true, is_current: true },
        ],
      }))
    mocked.fileService.getSessionAuditEvents.mockResolvedValue({ data: { audit_events: [] } })
    mocked.fileService.updateSessionWorkspace.mockResolvedValue({
      data: {
        session: {
          id: 42,
          permissions: { can_manage: true },
          workspace: { type: 'institution', institution: { id: 7, name: 'Museum Network' } },
          publishing_context: { effective_credential_source: 'user' },
        },
      },
    })

    const wrapper = mount(SessionGovernanceDrawer, {
      props: {
        open: true,
        session: {
          id: 42,
          permissions: { can_manage: true },
          workspace: { type: 'personal', institution: null },
          publishing_context: { effective_credential_source: 'user' },
        },
      },
    })

    await flushPromises()
    expect(mocked.fileService.getSessionWorkspace).toHaveBeenCalledWith(42, {})
    expect(wrapper.text()).toContain('Only the session owner can download raw .hdpc files.')
    expect(wrapper.text()).toContain('sanitized shared .hdpc export')

    const institutionToggle = wrapper.findAll('button').find((button) => button.text() === 'Institution')
    await institutionToggle.trigger('click')
    await flushPromises()

    expect(mocked.fileService.getSessionWorkspace).toHaveBeenNthCalledWith(2, 42, { institution_id: '7' })
    expect(wrapper.html()).toContain('Manager User (manager)')

    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save changes')
    await saveButton.trigger('click')
    await flushPromises()

    expect(mocked.fileService.updateSessionWorkspace).toHaveBeenCalledWith(42, {
      institution_id: 7,
      sharing_scope: 'private',
      credential_preference: 'user',
      publishing_user_id: 2,
      default_zenodo_environment: 'sandbox',
      use_institution_default_communities: false,
    })
    expect(wrapper.emitted('updated')?.[0]?.[0]?.workspace?.institution?.id).toBe(7)
  })

  it('hides audit history when the viewer cannot manage the session', async () => {
    mocked.fileService.getSessionWorkspace.mockResolvedValue(
      buildWorkspaceDetails({
        canManage: false,
      }),
    )
    mocked.fileService.getSessionAuditEvents.mockResolvedValue({ data: { audit_events: [] } })

    const wrapper = mount(SessionGovernanceDrawer, {
      props: {
        open: true,
        session: {
          id: 42,
          permissions: { can_manage: false },
          workspace: { type: 'personal', institution: null },
          publishing_context: { effective_credential_source: 'user' },
        },
      },
    })

    await flushPromises()

    expect(mocked.fileService.getSessionAuditEvents).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('Recent Session Audit')
  })

  it('shows explorer-only import badges when the session came from a shared export', async () => {
    mocked.fileService.getSessionWorkspace.mockResolvedValue(
      buildWorkspaceDetails({
        currentWorkspace: {
          institution_id: null,
          origin_type: 'hdpc_import',
          access_mode: 'explorer_only',
        },
      }),
    )
    mocked.fileService.getSessionAuditEvents.mockResolvedValue({ data: { audit_events: [] } })

    const wrapper = mount(SessionGovernanceDrawer, {
      props: {
        open: true,
        session: {
          id: 42,
          permissions: { can_manage: true },
          origin_type: 'hdpc_import',
          access_mode: 'explorer_only',
          workspace: { type: 'personal', institution: null },
          publishing_context: { effective_credential_source: 'user' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Explorer-only')
    expect(wrapper.text()).toContain('Imported .hdpc')
    expect(wrapper.text()).toContain('workflow and publishing mutations are blocked')
  })
})
