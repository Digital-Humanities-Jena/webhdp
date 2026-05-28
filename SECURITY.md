# Security Policy

## Supported Versions

The cleaned repository is currently pre-release. Security fixes should target the default branch unless a maintained release branch exists.

## Reporting a Vulnerability

Do not open public issues for vulnerabilities or leaked credentials.

Report privately to the repository owner or maintainer through the private contact channel configured on GitHub or Codeberg. Include:

- A concise description of the issue.
- Steps to reproduce.
- Affected routes, services, or deployment settings.
- Whether credentials, user data, publication tokens, HPC access, or uploaded files may be exposed.

## Secret Handling

- Never commit `.env`, service-account JSON, API tokens, SSH keys, local databases, logs, or session directories.
- Rotate any credential that was committed, copied into an issue, or exposed in logs.
- Use `CREDENTIAL_ENCRYPTION_KEY` in production instead of relying on `SECRET_KEY` fallback encryption.
- WebHDP stores user and institution Zenodo API keys encrypted at rest and returns only masked previews. Cleartext tokens must not appear in API responses, validation reports, audit logs, frontend state, screenshots, or documentation examples.
- Zenodo key sharing grants approved access to an encrypted credential record. It does not reveal the cleartext token to the recipient, administrators, or other users.
- HPC-Link deployment files must use operator-provided `HPC_HOST`, `HPC_USER`, VPN, SSH, admin, and token secrets. Do not commit institution-specific usernames, VPN secrets, SSH keys, known-host files, allocation names, or private cluster paths.
- Keep HPC-Link API tokens out of URLs. Prefer bearer/header auth and session storage only for the browser session.
