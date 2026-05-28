# Security and Credentials

This page explains how WebHDP protects sign-in secrets, Zenodo API keys, shared credential access, and recovery codes.

## Zenodo API Key Storage

User and institution Zenodo keys are stored in the `zenodo_credentials.encrypted_value` database field. WebHDP encrypts that value with Fernet through `services/credential_crypto.py`.

Production deployments must configure `CREDENTIAL_ENCRYPTION_KEY`. If that key is missing in production, credential encryption configuration is invalid and startup checks should fail. Development environments can fall back to `SECRET_KEY`, and finally to a development-only fallback secret, but that fallback is not appropriate for production data.

The readable token is only decrypted at the point where WebHDP must call Zenodo. It is not returned to the browser after saving.

## What Users And APIs Can See

Credential API responses return non-secret metadata only:
- key name
- Sandbox or Production environment
- ownership or share source
- active-key state
- masked preview
- validation status and validation report

Cleartext Zenodo tokens must not appear in API responses, validation reports, audit logs, frontend state, screenshots, documentation examples, task history, or `.hdpc` outputs.

## Sharing Zenodo Keys

Sharing a Zenodo key grants approved use of the encrypted credential record. It does not reveal the readable token to the recipient, administrators, or other users.

Recipients can accept or decline a share. Accepted shares can be selected as active keys for the matching environment. Owners can revoke shares, and revocation clears matching active-key selections for the recipient.

## Validation Safety

Zenodo credential validation uses the `live_write_cleanup` mode:
- authenticate against the selected Sandbox or Production API
- list depositions with a small read probe
- create a temporary validation draft when the token has the required scopes
- delete that temporary draft during cleanup

Validation reports record status, messages, scope recommendations, HTTP status codes, and probe names. They do not record the cleartext token.

## Passwords And Recovery Codes

WebHDP stores account passwords as password hashes, not readable passwords.

User recovery codes are generated once, displayed once, and then stored as HMAC hashes. WebHDP tracks whether a recovery code is available, used, expired, or invalidated. The raw recovery code is not redisplayed after generation.

Administrators can issue temporary recovery access for a user. That flow creates a temporary password and one-time recovery code for out-of-band handoff, then requires the user to change the password before continuing.

## Operational Expectations

Operators should:
- set `CREDENTIAL_ENCRYPTION_KEY` separately from `SECRET_KEY`
- rotate any credential that was committed, copied into an issue, pasted into a log, or exposed in a screenshot
- keep `.env`, service-account JSON, local databases, logs, and session directories out of Git
- verify backups and screenshots do not expose cleartext credentials

## Related Documentation

- [Zenodo API Keys](zenodo_api_keys.md)
- [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md)
- [Metadata And Retrieval Walkthroughs](video_guides/metadata_and_retrieval.md)
- [WebHDP API Reference](../api/webhdp_api_reference.md)
