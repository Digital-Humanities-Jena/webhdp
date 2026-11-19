# Access, Setup, And Identity Workflows

This document covers workflows that establish access to WebHDP before users can
run publishing, retrieval, or operator tasks.

## Overview

These workflows are the front door to WebHDP. They cover system setup, user
registration, sign-in, MFA, recovery, onboarding, and account maintenance. Most
readers only need the workflow that matches the current access problem; the
maintainer notes at the bottom explain where state and failure handling live.

## Use Cases

- Bring a fresh deployment from setup mode into normal authenticated use.
- Register and verify new users before they enter publication or retrieval workflows.
- Troubleshoot login, MFA, recovery-code, logout, onboarding, or forced password-change gates.
- Maintain account profile, password, onboarding, and recovery-code state.

## First-Time Setup

Primary actor: initial operator or administrator.

Entry points:
- UI: `/setup`
- API: `/api/v1/setup/status`
- API: `/api/v1/setup/check`
- API: `/api/v1/setup/create-admin`
- API: `/api/v1/setup/complete`
- API: `/api/v1/setup/test-render`
- API: `/api/v1/setup/reset`

Workflow:
1. Open the setup page with an authorized setup token or admin session.
2. Check whether the system is already initialized.
3. Run dependency checks for renderer and Zenodo reachability.
4. Create the first administrator account when needed.
5. Run the optional test-render smoke workflow when local renderer execution is allowed.
6. Mark setup complete so normal authenticated workflows can start.
7. Use reset only when an administrator intentionally returns the deployment to setup mode.

Complete when:
- Setup status reports initialized.
- An administrator can sign in.
- Required dependency checks match the intended deployment mode.

## Registration and email verification

1. Open **Create an account** at `/register`. Enter the email address you can
   receive mail at and select **Send verification email**.
2. Open the link in the WebHDP message. The browser opens `/verify-email`.
   Choose a password of 8 to 128 characters and select **Verify email and
   create account**. This action creates a verified account or activates an
   eligible account that was left unverified by an older release.
3. Sign in. A regular new account can start with personal projects, the
   guided tour, or the 3D tutorial. Open the original invitation email to join
   an [institution workspace](institutions-credentials-governance.md#invite-and-join-a-workspace).

Use **Resend verification email** on the registration page if the original
message is missing. If WebHDP reports an email delivery failure, request a new
link once the service is available. Use the newest message after a successful
resend. The default resend cooldown is one minute, and links expire after
24 hours by default.

Registration links contain a one-time secret in the URL fragment. Activation
requires a password submitted explicitly from the page. WebHDP stores a hash
of the secret and consumes it atomically on successful activation. Treat the
message as private.

The public API uses `POST /api/v1/auth/register` and
`POST /api/v1/auth/resend-verification` with an email address. Submit the link
token and new password to `POST /api/v1/auth/verify-email`.
[Authentication API](../api/webhdp_api_reference.md#6-auth-api-apiv1auth)

### Existing accounts and older links

Already verified accounts keep their passwords and access after upgrade.
Verification links from earlier releases expire during migration. An
unverified user can request a fresh link through **Resend verification**.

WebHDP validates email addresses and compares a case-insensitive account key.
Mail uses the destination mailbox spelling. Existing accounts with colliding
addresses are preserved individually, and their exact stored sign-in addresses
remain usable by verified owners. Ask account support to review a collision
before activating pending accounts or accepting an invitation for that
address.

## Guided account setup

From **Getting started**, select **Open account setup**. You can also open
**Account setup** from **Account Configuration** or go to `/account/setup`. This
guide is available to regular signed-in users after registration and on
return visits.

1. Review the separate Sandbox and Production key statuses. Open the
   existing credential controls to add, select, and validate a key for the
   environment you plan to use. A Sandbox credential is needed for the
   Sandbox deposit workflow. The built-in 3D practice workflow can be used
   immediately after sign-in.
2. Search for a visible institution workspace. For an existing workspace,
   request an invitation from its manager and accept the invitation with
   the verified email it was sent to. Use the workspace request form if you
   need a new institution workspace. A site administrator reviews the
   request.
3. When you manage a workspace, open it from the guide to send invitations
   and review existing ones. Follow its assigned role rules when choosing
   which access to grant. In **Institution Workspaces**, a manager or owner
   can set **Directory visibility** to **Visible to signed-in users** to make
   it searchable. A new member still needs an invitation. New workspaces are
   **Private** by default.

Choose the steps relevant to your work and return whenever your key or
workspace status changes. [Zenodo API keys](../guides/zenodo_api_keys.md) ·
[Institution workspaces](institutions-credentials-governance.md)

### Verification delivery checks

Run registration and invitation checks with a mailbox controlled by the
deployment operator. For local tests, send mail to a loopback SMTP sink. For
staging, use the configured SMTP relay and at least one mailbox on the
institution's expected mail domain.

1. Check that the test message arrives and its link opens the expected
   `FRONTEND_URL` over HTTPS.
2. Test a resend and complete activation using the newest message. Confirm
   sign-in works and verification-link reuse is rejected.
3. On staging, temporarily make SMTP unavailable and confirm the form reports
   the delivery failure. Restore SMTP, resend, and complete registration.
4. Send and accept an invitation using a second controlled mailbox if
   institution workflows are enabled.

`MAIL_TIMEOUT` bounds SMTP operations and defaults to five seconds. Match the
configured SMTP port and TLS mode to the mail provider. SMTP acceptance and
mailbox receipt are separate checks. Use the same writable, private instance
directory for authentication throttling across API workers. Proxy trust
configuration is covered in the [operations guide](../guides/operations_and_setup_guide.md).

## Login, MFA, Recovery Login, And Logout

Primary actor: any user.

Entry points:
- UI: `/login`
- API: `/api/v1/auth/login`
- API: `/api/v1/auth/login/verify-code`
- API: `/api/v1/auth/login/resend-code`
- API: `/api/v1/auth/login/verify-recovery-code`
- API: `/api/v1/auth/logout`

Workflow:
1. Submit credentials.
2. If MFA is required, verify the emailed code or use a recovery code.
3. Resend the MFA code when allowed by cooldown policy.
4. Receive an access token and continue to authenticated pages.
5. Logout to revoke the active session token.

Complete when:
- The authenticated user context is available, or the logout token is revoked.

## Account Profile, Password, Recovery Codes, And Onboarding

Primary actor: authenticated user.

Entry points:
- UI: `/account/configuration`
- UI: `/onboarding`
- UI: `/tutorial/3d`
- API: `/api/v1/auth/me`
- API: `/api/v1/auth/me/password`
- API: `/api/v1/auth/me/recovery-codes`
- API: `/api/v1/auth/me/onboarding`

Workflow:
1. Load the current account profile.
2. Update user profile fields, visibility preferences, password, and recovery codes as needed.
3. On first sign-in, open **Getting started** to take the four-step tour, try the 3D tutorial, or continue to your workspace. **Getting started** remains available after onboarding.
4. If forced password change is active, complete the password update before navigation continues.

Complete when:
- The user profile is saved.
- New users can finish or skip the introduction. Tour progress resumes in the same browser and the tour can be replayed.
- The [3D tutorial](../guides/model_publication.md#practise-with-the-3d-tutorial) can be run again from **Getting started** with a verified account.
- Recovery codes exist when MFA recovery is required.

## Prerequisites And Permissions

- Setup requires a valid setup token or an existing administrator session.
- Registration requires working verification email delivery.
- MFA login and recovery-code login require MFA configuration and previously issued codes.
- Account profile and onboarding updates require an authenticated user session.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Setup checks and admin form | Initialized deployment | setup status, first admin user, renderer check result |
| Email address, verification link and chosen password | Verified user account | delivery status, link expiry and consumption |
| Login credentials, MFA code, or recovery code | Authenticated session token | token revocation, MFA cooldowns, recovery-code consumption |
| Account profile and password changes | Updated user security state | `force_password_change`, onboarding flags, recovery-code availability |

## Failure And Recovery

- Failed setup checks should be resolved before marking setup complete.
- Expired or retired verification links require a fresh link from the
  registration page.
- MFA delivery issues can be recovered through resend or recovery-code login when available.
- If you cannot remember your password, contact account support. A recovery
  code can complete MFA after the correct password is entered.
- Forced password-change loops should be diagnosed from the current user profile and router guard state.

## Optimization Targets

- Reduce setup friction by making dependency failures actionable.
- Keep MFA resend, recovery, and cooldown behavior predictable.
- Avoid repeated current-user fetches during router navigation.
- Keep onboarding gates explicit so users know why a workflow is blocked.

## Verification Checklist

- Verify setup status, dependency check, admin creation, and setup completion.
- Test registration, resend, explicit verification, sign-in, MFA,
  recovery-code sign-in, and sign-out.
- Rehearse actual verification and invitation delivery on staging with
  controlled mailboxes.
- Confirm forced password-change and onboarding guards route users correctly.
- Confirm account profile, password, and recovery-code updates persist.

Related docs:
- `docs/guides/security_and_credentials.md`
- `docs/guides/video_guides/installation_and_setup.md`
- `docs/guides/video_guides/release_walkthroughs.md`

## Codebase Starting Points

- Frontend setup/auth views: `frontend/src/views/setup/`, `frontend/src/views/auth/`
- Account and onboarding views: `frontend/src/views/account/`, `frontend/src/views/onboarding/`
- Frontend auth store and guards: `frontend/src/stores/auth.js`, `frontend/src/router/index.js`
- Setup routes: `routes/setup_routes.py`
- Authentication and account routes: `routes/auth_routes.py`
- Registration and shared throttling: `services/registration_service.py`, `services/auth_throttle.py`
- SMTP sender: `services/email_service.py`
- User, MFA, token, and recovery models: `database/models.py`
- Security and credential helpers: `services/zenodo_credential_service.py`, `services/credential_crypto.py`, `services/notification_service.py`
