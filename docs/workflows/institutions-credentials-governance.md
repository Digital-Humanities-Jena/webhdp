# Institutions, Credentials, And Governance Workflows

This document covers personal credentials, institution credentials, institution
workspaces, community policy, and admin user governance.

## Overview

These workflows describe how WebHDP decides who may publish, which Zenodo
credential is used, and how institution-level policy is managed. They cover
personal credentials, credential sharing, institution membership, institution
communities, institution credentials, and admin user controls.

## Use Cases

- Request an institution workspace, invite members, and manage communities,
  publishing credentials, and audit history.
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

## Request or administer a workspace

Open **Institution Workspaces** at `/account/institutions`. A verified account
can use **Request an institution workspace** to submit the institution name and
an optional purpose. The page shows the current decision, any review note, and a
link to an approved workspace. Each account can have up to five requests pending.

A site administrator opens **Workspace requests**, checks the identity of the
organization and the requester's authority to represent it, and selects
**Approve** or **Reject**. Approval creates a private workspace and grants the
requester its initial Owner membership in the same transaction. For an
existing workspace, direct the requester to its manager for an invitation.
Name matching is Unicode-aware and accounts for differences in case and
punctuation.

Site administrators can also create an institution directly or open an existing
workspace in the institution list. The administrator who creates a workspace
directly becomes its first Owner. Invite the responsible colleague as an
Owner and confirm their acceptance before changing the initial ownership.
Site administrators can change the official institution name. Managers and
owners manage the institution's working settings.

Under **Directory visibility**, managers and owners can keep a workspace
**Private** or choose **Visible to signed-in users** and save the workspace.
Visibility lets signed-in users find the workspace during account setup.
Membership still starts with an accepted invitation.

Affiliation is descriptive profile information. In **Account settings**, an
individual can enter a label or select a visible institution. An accepted
membership is required to use that institution's workspace. If a private
institution is your employer or project partner, ask a manager for an invitation.
[Institution API](../api/webhdp_api_reference.md#16-institution-api-apiv1institutions)

## Invite and join a workspace

1. A manager or owner opens the workspace and uses **Invite someone**. Enter
   the intended recipient's email and select a role. The recipient can
   register after receiving the invitation.
2. The recipient opens the invitation email and signs in with the verified
   address that received it. If they need a WebHDP account, they confirm the
   separate verification email and then reopen the original invitation link.
   [Registration workflow](access-setup-identity.md#registration-and-email-verification)
3. WebHDP previews the workspace and offered role. The recipient selects
   **Accept invitation**, then **Open institution workspace**. When the
   recipient already has a membership, their existing role remains in effect.

The manager's **Invitations** list shows pending, accepted, revoked, and
expired invitations. A pending invitation can be resent or revoked. A
successful resend issues a fresh link and retires the previous one. A failed
resend keeps the previous valid link available and stays visible for retry.
Links expire after seven days. A recipient can receive a resend
after one minute, and each institution can request up to 60 sends per hour.
Invitations to become Owner can be issued and managed by current owners and
site administrators.

Invitation secrets travel in the email link's URL fragment. WebHDP stores
their hashes and requires the recipient's authenticated, verified email for
preview and explicit acceptance. Acceptance also checks the issuer's current
permission and consumes the invitation atomically. Share the link only with
the intended recipient.

## Workspace roles and member privacy

| Role | Workspace access |
| --- | --- |
| Reader | View sessions explicitly shared with the institution. |
| Curator | View, edit, and run shared sessions within their session permissions. |
| Manager | Manage working settings, communities, credentials, ordinary invitations, existing memberships, and the institution audit log. |
| Owner | Manage the workspace and its owners. The workspace keeps at least one Owner. |

An institution owner or site administrator must approve changes to an Owner
membership. A person who leaves the institution can be removed from
**Members**. Use **Invitations** to revoke an invitation that has yet to be
accepted. Membership changes are audited with the grant or removal.

The roster and audit actor details respect members' profile visibility and
email choices. A workspace role grants access to shared sessions, and private
sessions retain their own access policy. Institution managers can review audit
entries for the sessions they may see. Site administrators can audit the
whole workspace under site-level permissions.

On upgrade, review legacy workspace owners and Reader memberships before
enabling institutional use. Older releases could create a workspace through
profile affiliation or assign Reader when a user selected an existing
institution. The migration preserves the existing assignments so operators can
review them against institution approvals.

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

The workspace credential preference determines what WebHDP checks first. An
active personal credential can be used by its owner and users with an accepted
share. An institution credential can be used by a curator, manager or owner of
that institution and by site moderation staff. For `User` preference without
an active personal credential, WebHDP checks the institution credential if the
session and user qualify. For a separate actor without access to the selected
personal key, choose `Institution` or arrange an accepted share.

Ordinary accounts use an authorized credential for the chosen environment.
They cannot use the site's Production credential. An operator can deliberately
enable Sandbox fallback for regular workflows by configuring both
`ZENODO_SANDBOX_API_KEY` and `WEBHDP_ALLOW_SYSTEM_SANDBOX_PUBLISHING=true`.
The restricted Model Publication demo uses its separately configured Sandbox
credential. A workflow with no Zenodo step or remote versioning action can run
without a credential. Queued writes check the initiating user again when they
start, including current session access and any credential share required.

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
- Workspace requests require a verified account. Only site administrators
  approve a request or create an official institution directly.
- New membership requires acceptance by the verified invite recipient.
  Institution managers or owners manage existing ordinary memberships and
  invitations. Institution credentials and community policies require manager
  or site administrator rights.
- Admin user governance requires administrator access.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Personal Zenodo token and environment | Encrypted named credential | active credential, validation status, environment |
| Share invite or share action | Accepted, declined, or revoked share | share state, recipient access, owner visibility |
| Institution profile, memberships, and communities | Governed institution workspace | member roles, audit events, community policy |
| Workspace request and administrator decision | Private workspace with initial Owner, or rejection and review note | pending, approved, rejected |
| Invitation email and verified recipient decision | Membership with the accepted role | pending, accepted, revoked, expired |
| Institution Zenodo credential | Institution-level publishing credential | credential validation, fallback resolution |
| Admin role and capability changes | Updated user governance state | role, capability flags, recovery reset state |

## Failure And Recovery

- Failed credential validation should identify sandbox/production mismatch, missing scope, or write probe failure.
- Declined or revoked shares require a new share workflow before the recipient can use the credential.
- For a missing invitation, check the address and ask a manager to resend.
  A recipient with a different account should sign out and use the verified
  address that received the invitation.
- If the invite issuer lost permission or the invitation expired or was
  revoked, an authorized manager or owner can issue a new invitation.
- When a legacy address matches multiple accounts, ask account support to
  resolve the identity before accepting the invitation.
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
- Verify workspace request, approval and rejection. Check that approval
  creates a private workspace owned by the requester and appears in both the
  requester and administrator views.
- Verify invite delivery, registration of a new recipient, preview,
  acceptance, resend, revocation, and rejection of wrong-account or expired
  links. Confirm the roster and audit log respect private profiles.
- Verify affiliation, role changes, communities, and the last-owner guard.
- Verify institution credential save/delete/validate and publication credential resolution.
- Verify admin role, capability, and recovery reset changes.

Related docs:
- `docs/guides/zenodo_api_keys.md`
- `docs/guides/security_and_credentials.md`
- `docs/guides/video_guides/metadata_and_retrieval.md`

## Codebase Starting Points

- Institution workspace frontend: `frontend/src/views/account/InstitutionWorkspaceView.vue`
- Invitation acceptance frontend: `frontend/src/views/account/InstitutionInvitationView.vue`
- Account configuration frontend: `frontend/src/views/account/AccountConfigurationView.vue`
- Institution and invitation routes: `routes/institution_routes.py`, `routes/institution_invitation_routes.py`
- Approval and invitation services: `services/institution_workspace_request_service.py`, `services/institution_invitation_service.py`
- Credential and auth routes: `routes/auth_routes.py`
- Admin user governance: `routes/admin_routes.py`
- Credential resolution and encryption: `services/zenodo_credential_service.py`, `services/credential_crypto.py`
- Institution and credential models: `database/models.py`
