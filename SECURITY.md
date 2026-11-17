# Security Policy

## Supported Versions

WebHDP is in alpha. Security fixes should target the default branch unless a
maintained release branch exists.

## Reporting a Vulnerability

Do not open public issues for vulnerabilities or leaked credentials.

Use [private vulnerability reporting](https://github.com/Digital-Humanities-Jena/webhdp/security)
if enabled, or contact the repository maintainer privately. Include:

- A concise description of the issue.
- Steps to reproduce.
- Affected routes, services, or deployment settings.
- Whether credentials, user data, publication tokens, HPC access, or uploaded files may be exposed.

## Secret Handling

- Never commit `.env`, service-account JSON, API tokens, SSH keys, local databases, logs, or session directories.
- Revoke and rotate any credential that was committed, copied into an issue, or
  exposed in logs. Removing it from the latest commit does not revoke it or
  remove it from Git history.
- Use a random production `SECRET_KEY` of at least 32 bytes for HS256 JWT
  signing. Use a separate `CREDENTIAL_ENCRYPTION_KEY` in production instead of
  relying on development fallback encryption.
- WebHDP stores user and institution Zenodo API keys encrypted at rest and returns only masked previews. Cleartext tokens must not appear in API responses, validation reports, audit logs, frontend state, screenshots, or documentation examples.
- Zenodo key sharing grants approved access to an encrypted credential record. It does not reveal the cleartext token to the recipient, administrators, or other users.
- HPC-Link deployment files must use operator-provided `HPC_HOST`, `HPC_USER`, VPN, SSH, admin, and token secrets. Do not commit institution-specific usernames, VPN secrets, SSH keys, known-host files, allocation names, or private cluster paths.
- Keep HPC-Link service tokens, SSH identity and gateway administration
  credentials on the backend or operator systems. The presenter and audience
  do not need gateway credentials to use or view a pre-reserved GPU demo.
- Use exact origins and callbacks for WebHDP-Link, keep browser tokens in
  memory and hold service tokens in a private secret store. Review proxy and
  application logs for query, header and request body logging before enabling
  clients. Use isolated execution for untrusted component code.

See [Security and Credentials](docs/guides/security_and_credentials.md) for
the application credential lifecycle and [Publishing WebHDP](PUBLISHING.md) for
the release-tree review.
