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

The account profile displays the verified sign-in email as read-only. Contact
the WebHDP operator when the sign-in address needs to change. Profile fields
such as display name and affiliation can be edited independently of the
account's verified address and workspace membership.

User recovery codes are generated once, displayed once, and then stored as HMAC hashes. WebHDP tracks whether a recovery code is available, used, expired, or invalidated. The raw recovery code is not redisplayed after generation.

Administrators can issue temporary recovery access for a user. That flow creates a temporary password and one-time recovery code for out-of-band handoff, then requires the user to change the password before continuing.

## Operational Expectations

Operators should:
- use a random production `SECRET_KEY` of at least 32 bytes for HS256 JWT
  signing and set `CREDENTIAL_ENCRYPTION_KEY` separately
- rotate any credential that was committed, copied into an issue, pasted into a log, or exposed in a screenshot
- keep `.env`, service-account JSON, local databases, logs, and session directories out of Git
- verify backups and screenshots do not expose cleartext credentials

## Connected Applications

WebHDP-Link registers exact application origins and callbacks. It uses
authorization code with S256 PKCE for browser consent and scopes access to
the approved client, verified user and pipeline publications. The browser
SDK holds Link access tokens in memory. Keep tokens out of persistent browser
storage, callback URLs, telemetry and logs. A separate administrator-issued
service token is for trusted server-side use only. Use a short lifetime and
a secret store. Revoking a grant can stop authorized work at a subsequent
execution boundary; ordinary browser token expiry allows the user to reconnect
and track work already accepted.

Link publications can use only installed, reviewed components. A native host
CLI runs as the worker's OS identity and is not a filesystem sandbox. Use an
isolated runtime for untrusted tools. The approved Sandbox upload component
receives only the initiating user's active Sandbox credential at invocation;
never put it in a pipeline parameter, image or HPC environment. Treat private
Link data and its encryption key as separate backup material.

## Reserved GPUs

The browser does not receive gateway or SSH credentials. Use a separate
administrator credential to register an operator-held scheduler job in the
private gateway. Delegate the opaque registration to WebHDP's restricted
service principal. WebHDP grants access only to named verified accounts with
HPC Access. A claim is bound to the claimant's upload session. Only release an
idle claim; detachment does not cancel the Slurm job. Protect the gateway
registry, cluster identity and artifact workspace with private mounts.

When cloud staging is enabled, the gateway checks HTTPS destination, expected
host and public address for every request and redirect. Raw object references
sent from WebHDP must match recorded mirrors of that upload session. When a
native pipeline is authorized to upload a Zenodo draft remotely, it supplies
the credential through standard input and the HTTPS Authorization header,
without writing the credential to a remote file. It uploads only regular
outputs to the selected Zenodo origin. This is separate from the local-only
WebHDP-Link Sandbox example.

## Related Documentation

- [Zenodo API Keys](zenodo_api_keys.md)
- [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md)
- [Metadata And Retrieval Walkthroughs](video_guides/metadata_and_retrieval.md)
- [WebHDP API Reference](../api/webhdp_api_reference.md)
- [WebHDP-Link deployment runbook](webhdp_link_deployment.md)
- [Pre-reserved GPU runbook](prereserved_gpu_demo.md)
