# Institutions, Credentials, And Governance Workflows

This document covers personal credentials, institution credentials, institution
workspaces, community policy, and admin user governance.

## Overview

These workflows describe how WebHDP decides who may publish, which Zenodo
credential is used, and how institution-level policy is managed. They cover
personal credentials, credential sharing, institution membership, institution
communities, institution credentials, and admin user controls.

## Use Cases

- Manage institutional membership, affiliation, communities, and audit history.
- Share, accept, decline, revoke, or validate personal and institution Zenodo credentials.
- Resolve publishing credentials when work is done on behalf of an institution.
- Manage user roles, capabilities, and recovery reset flows.

## Personal Zenodo Credentials

Primary actor: authenticated user.

Entry points:
- UI: `/account/configuration`
- API: `/api/v1/auth/me/zenodo-credentials`
- API: `/api/v1/auth/me/zenodo-credentials/<environment>`
- API: `/api/v1/auth/me/zenodo-credentials/<credential_id>`
- API: `/api/v1/auth/me/zenodo-credentials/<environment>/validate`
- API: `/api/v1/auth/me/zenodo-credentials/<credential_id>/validate`
- API: `/api/v1/auth/me/zenodo-active-credentials/<environment>`

Workflow:
1. Create or update named Sandbox and Production credentials.
2. Validate the credential.
3. Rename or delete credentials when needed.
4. Select one active credential per environment for publishing.

Complete when:
- The intended key is saved, active, and valid for the target environment.

## Credential Sharing

Primary actor: credential owner and recipient.

Entry points:
- API: `/api/v1/auth/me/zenodo-credentials/<credential_id>/share`
- API: `/api/v1/auth/me/zenodo-credential-shares/<share_id>/accept`
- API: `/api/v1/auth/me/zenodo-credential-shares/<share_id>/decline`
- API: `/api/v1/auth/me/zenodo-credential-shares/<share_id>`

Workflow:
1. Owner creates a credential share invitation.
2. Recipient accepts or declines the share.
3. Owner revokes the share when access should end.
4. Publishing context can use accepted shares without exposing cleartext tokens.

Complete when:
- Share state reflects the intended access policy.

## Institution Workspace And Memberships

Primary actor: administrator, institution manager, or user configuring affiliation.

Entry points:
- UI: `/account/institutions`
- API: `/api/v1/institutions`
- API: `/api/v1/institutions/suggestions`
- API: `/api/v1/institutions/affiliation`
- API: `/api/v1/institutions/<institution_id>`
- API: `/api/v1/institutions/<institution_id>/memberships`
- API: `/api/v1/institutions/<institution_id>/memberships/<member_user_id>`
- API: `/api/v1/institutions/<institution_id>/audit-events`

Workflow:
1. Suggest or create an institution.
2. Configure a user's affiliation.
3. Add, update, or remove institution memberships.
4. Review institution audit events.
5. Use institution context during publishing.

Complete when:
- Membership and affiliation state matches the intended workspace governance.

## Institution Communities And Community Policy

Primary actor: institution manager or administrator.

Entry points:
- API: `/api/v1/institutions/<institution_id>/communities`
- API: `/api/v1/institutions/<institution_id>/communities/<community_id>`
- API: `/api/v1/admin/zenodo-community-config`

Workflow:
1. Configure institution-level Zenodo communities.
2. Set moderation defaults and primary submission community policy.
3. Use global community override only when deployment policy requires it.

Complete when:
- Community policy resolves correctly for publication and moderation workflows.

## Institution Zenodo Credentials

Primary actor: institution manager or administrator.

Entry points:
- API: `/api/v1/institutions/<institution_id>/zenodo-credentials/<environment>`
- API: `/api/v1/institutions/<institution_id>/zenodo-credentials/<environment>/validate`

Workflow:
1. Save or update institution Sandbox and Production credentials.
2. Validate write capability.
3. Remove credentials when revoked or retired.
4. Allow publishing context resolution to fall back to institution credentials when user credentials are not selected.

Complete when:
- Institution credentials are valid and available for eligible workspace publishing.

## Admin User Governance

Primary actor: administrator.

Entry points:
- UI: `/admin/dashboard`
- API: `/api/v1/admin/users`
- API: `/api/v1/admin/users/<user_id>/role`
- API: `/api/v1/admin/users/<user_id>/capabilities`
- API: `/api/v1/admin/users/<user_id>/recovery-reset`

Workflow:
1. List users.
2. Change roles.
3. Grant or revoke capabilities such as pipeline authoring or developer access.
4. Reset recovery hardening state for a user when needed.

Complete when:
- User role, capability, and recovery state are consistent with governance policy.

## Prerequisites And Permissions

- Personal credential workflows require an authenticated user.
- Credential sharing requires a credential owner and a recipient account.
- Institution membership, community policy, and institution credentials require institution manager or administrator rights.
- Admin user governance requires administrator access.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Personal Zenodo token and environment | Encrypted named credential | active credential, validation status, environment |
| Share invite or share action | Accepted, declined, or revoked share | share state, recipient access, owner visibility |
| Institution profile, memberships, and communities | Governed institution workspace | member roles, audit events, community policy |
| Institution Zenodo credential | Institution-level publishing credential | credential validation, fallback resolution |
| Admin role and capability changes | Updated user governance state | role, capability flags, recovery reset state |

## Failure And Recovery

- Failed credential validation should identify sandbox/production mismatch, missing scope, or write probe failure.
- Declined or revoked shares require a new share workflow before the recipient can use the credential.
- Institution credential issues should fall back to personal credentials only when policy allows it.
- Role or capability mistakes should be corrected through admin user governance and audited.

## Optimization Targets

- Keep credential resolution predictable across personal, shared, and institution contexts.
- Minimize live Zenodo validation calls while preserving clear confidence.
- Make institution membership and community policy queries efficient for large organizations.
- Keep audit events useful without slowing normal workspace actions.

## Verification Checklist

- Verify create/update/list/delete/validate personal credentials.
- Verify share, accept, decline, and revoke flows.
- Verify institution create/update, affiliation, memberships, communities, and audit events.
- Verify institution credential save/delete/validate and publication credential resolution.
- Verify admin role, capability, and recovery reset changes.

Related docs:
- `docs/guides/zenodo_api_keys.md`
- `docs/guides/security_and_credentials.md`
- `docs/guides/video_guides/metadata_and_retrieval.md`

## Codebase Starting Points

- Institution workspace frontend: `frontend/src/views/account/InstitutionWorkspaceView.vue`
- Account configuration frontend: `frontend/src/views/account/AccountConfigurationView.vue`
- Institution routes: `routes/institution_routes.py`
- Credential and auth routes: `routes/auth_routes.py`
- Admin user governance: `routes/admin_routes.py`
- Credential resolution and encryption: `services/zenodo_credential_service.py`, `services/credential_crypto.py`
- Institution and credential models: `database/models.py`
