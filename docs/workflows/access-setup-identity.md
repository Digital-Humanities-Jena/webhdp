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

## Registration And Email Verification

Primary actor: new WebHDP user.

Entry points:
- UI: `/register`
- UI: `/verify-email/:token`
- API: `/api/v1/auth/register`
- API: `/api/v1/auth/verify-email/<token>`

Workflow:
1. Submit an email and password.
2. Receive a verification token.
3. Open the verification URL.
4. Continue to sign in after the account is verified.

Complete when:
- The user account is verified and can authenticate.

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
- API: `/api/v1/auth/me`
- API: `/api/v1/auth/me/password`
- API: `/api/v1/auth/me/recovery-codes`
- API: `/api/v1/auth/me/onboarding`

Workflow:
1. Load the current account profile.
2. Update user profile fields, visibility preferences, password, and recovery codes as needed.
3. Complete required onboarding steps before using publishing workflows.
4. If forced password change is active, complete the password update before navigation continues.

Complete when:
- The user profile is saved.
- Required onboarding or forced password-change gates are cleared.
- Recovery codes exist when MFA recovery is required.

## Prerequisites And Permissions

- Setup requires a valid setup token or an existing administrator session.
- Registration requires the deployment to allow new accounts and, when enabled, email delivery for verification.
- MFA login and recovery-code login require MFA configuration and previously issued codes.
- Account profile and onboarding updates require an authenticated user session.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Setup checks and admin form | Initialized deployment | setup status, first admin user, renderer check result |
| Registration form and verification token | Verified user account | user verification status and email token lifecycle |
| Login credentials, MFA code, or recovery code | Authenticated session token | token revocation, MFA cooldowns, recovery-code consumption |
| Account profile and password changes | Updated user security state | `force_password_change`, onboarding flags, recovery-code availability |

## Failure And Recovery

- Failed setup checks should be resolved before marking setup complete.
- Expired or invalid verification tokens require a new verification flow.
- MFA delivery issues can be recovered through resend or recovery-code login when available.
- Forced password-change loops should be diagnosed from the current user profile and router guard state.

## Optimization Targets

- Reduce setup friction by making dependency failures actionable.
- Keep MFA resend, recovery, and cooldown behavior predictable.
- Avoid repeated current-user fetches during router navigation.
- Keep onboarding gates explicit so users know why a workflow is blocked.

## Verification Checklist

- Verify setup status, dependency check, admin creation, and setup completion.
- Test register, verify-email, login, MFA, recovery-code login, and logout paths.
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
- User, MFA, token, and recovery models: `database/models.py`
- Security and credential helpers: `services/zenodo_credential_service.py`, `services/credential_crypto.py`, `services/notification_service.py`
