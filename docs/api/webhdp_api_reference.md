# WebHDP API Reference

Base URLs, default development environment:
- `http://localhost:5000/api/v1`
- `http://localhost:5000/api/v2`

This document describes the WebHDP HTTP API under `/api/v1/...` and
`/api/v2/...`. For the connected application API, see [WebHDP-Link](#21-webhdp-link-api-apiv1link).

A generated route inventory is available at `openapi.json`. Regenerate it with `make api-contract` after adding or removing API routes.

Boundary notes:
- This document covers the WebHDP API only.
- It does not document the legacy HDP Server internal API surface.
- Session-local `.hdpc` query routes reflect the canonical `webhdp-local-2` schema described in `../architecture/hdpc_schema.md`.
- `/api/v2` currently hosts the native pipeline execution and run-status surface.

Workflow contract notes:
- Upload/scan ends at a `scanned` session and does not create submit-flow Zenodo records.
- First submit creates canonical records from selected files.
- Reruns and post-submit execution paths act on persisted `record_ids`.
- Canonical session states are `queued`, `scanned`, `submitting`, `completed`, and `failed`.

## 1. Response Conventions

### Success envelope
```json
{
  "success": true,
  "data": {},
  "message": "optional",
  "metadata": {}
}
```

### Error envelope
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {}
  }
}
```

## 2. Authentication and Access Model

- WebHDP JWT bearer authentication is required for protected native routes.
  WebHDP-Link has separate scoped tokens for external clients.
- Role values: `user`, `moderator`, `admin`.
- Additional access patterns appear throughout the API:
  - `Owner scope`: the authenticated user must own the session/submission or otherwise have explicit access.
  - `Session view/edit/manage`: enforced per-session by session governance helpers.
  - `Mutable session`: write routes reject read-only imported or explorer-only sessions.
  - `Institution member/manager`: institution routes distinguish read access from management access.
  - `Admin+Local`: route requires admin privileges and local storage mode.

## 3. Public and Compatibility Routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | No | Service liveness plus selected feature flags |
| GET | `/public/records/<environment>/<zenodo_record_id>` | No | Public presentation payload for a published Zenodo record |
| GET | `/oembed` | No | oEmbed provider endpoint for public WebHDP record pages |
| POST | `/sessions/file` | Yes | Single-file upload, session bootstrap, and local `.hdpc` scan |
| POST | `/start-pipeline` | Yes | Compatibility entrypoint for the predefined session pipeline |

### 3.1 Public Record Presentation

`GET /api/v1/public/records/<environment>/<zenodo_record_id>`

Returns a public, unauthenticated payload for a published Zenodo record that can be shown on WebHDP public pages and iframe embeds.

Path parameters:
- `<environment>`: `zenodo` or `sandbox`
- `<zenodo_record_id>`: Zenodo record identifier

The endpoint does not expose WebHDP session IDs or local record IDs. It derives title, creators, DOI, file list, thumbnail candidates, and 3D preview eligibility from public Zenodo metadata.

Example response:
```json
{
  "success": true,
  "data": {
    "environment": "zenodo",
    "zenodo_record_id": "12345",
    "title": "Public 3D Model",
    "creators": ["Ada Lovelace"],
    "doi": "10.5281/zenodo.12345",
    "zenodo_url": "https://zenodo.org/records/12345",
    "public_url": "https://webhdp.example.org/p/records/zenodo/12345",
    "embed_url": "https://webhdp.example.org/embed/records/zenodo/12345",
    "oembed_url": "https://webhdp.example.org/api/v1/oembed?url=...&format=json",
    "thumbnail_url": "https://zenodo.org/api/records/12345/files/model_preview.png/content",
    "model_preview": {
      "is_3d_record": true,
      "can_inline_preview": true,
      "url": "https://zenodo.org/api/records/12345/files/model.glb/content",
      "format": "glb"
    }
  }
}
```

### 3.2 oEmbed Provider

`GET /api/v1/oembed?url=<public_record_url>&format=json&maxwidth=<px>&maxheight=<px>`

Returns a standard JSON oEmbed response for public WebHDP record URLs:
- `/p/records/<environment>/<zenodo_record_id>`
- `/embed/records/<environment>/<zenodo_record_id>`

Query parameters:
- `url` required: public WebHDP record or embed URL
- `format` optional: only `json` is supported; XML returns `501`
- `maxwidth` optional: positive integer, used to bound iframe width
- `maxheight` optional: positive integer, used to bound iframe height

Example response:
```json
{
  "version": "1.0",
  "type": "rich",
  "title": "Public 3D Model",
  "provider_name": "WebHDP",
  "provider_url": "https://webhdp.example.org",
  "author_name": "Ada Lovelace",
  "html": "<iframe src=\"https://webhdp.example.org/embed/records/zenodo/12345\" width=\"640\" height=\"480\" title=\"Public 3D Model\" loading=\"lazy\" allowfullscreen style=\"border:0;max-width:100%;aspect-ratio:640/480;\"></iframe>",
  "width": 640,
  "height": 480,
  "thumbnail_url": "https://zenodo.org/api/records/12345/files/model_preview.png/content",
  "thumbnail_width": 640,
  "thumbnail_height": 480
}
```

Public frontend routes:
- `/p/records/<environment>/<zenodo_record_id>`: public landing page with oEmbed discovery metadata
- `/embed/records/<environment>/<zenodo_record_id>`: minimal iframe-safe preview page

Operational notes:
- Only published public Zenodo records are embeddable.
- `PUBLIC_BASE_URL` should be set to the externally reachable WebHDP origin when it differs from `FRONTEND_URL`.
- `OEMBED_FRAME_ANCESTORS` controls the embed route `frame-ancestors` CSP value. Keep it as narrow as practical in production.

## 4. Documentation API (`/api/v1/docs`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/index` | No | Documentation catalog for the in-app docs center |
| GET | `/content/<doc_id>` | No | Render a registered documentation page |
| GET | `/assets/<path:asset_path>` | No | Serve documentation-linked static assets |

## 5. Developer API (`/api/v1/developer`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/status` | Yes | Admin, moderator, or `developer_access` capability | Read-only onboarding diagnostics, developer docs links, non-secret runtime flags, and API contract status |

The developer status endpoint intentionally excludes secrets, database URLs, tokens, and private filesystem details. It is meant to power the in-app `/developer` page for contributors validating a local setup.

## 5.1 HDP Component Installer API (`/api/v1/tools/hdp-components`)

The HDP Component Installer API is admin-only and installs manifest-backed
components independently from the main WebHDP application. Components can use
one of two installation strategies:

- `local_container`: Docker-backed execution on a workstation-local WebHDP deployment.
- `hpc_sif`: Singularity SIF-backed execution through HPC-Link.

The native component registry remains component-version based. If the same
component version is installed for both strategies, WebHDP merges the local and
HPC execution profiles into one registered component version and keeps separate
installation records per strategy.

| Method | Path | Purpose |
|---|---|---|
| GET | `/tools/hdp-components/catalog?install_strategy=<strategy>&source=<source>` | List installable component manifests for `local_container` or `hpc_sif` from the local catalog, configured remote indexes, or both |
| GET | `/tools/hdp-components/catalog/diagnostics` | Inspect configured component index sources, cache state, current WebHDP version, and trust policy |
| POST | `/tools/hdp-components/validate` | Validate manifest, source artifact, Docker policy, or HPC-Link install readiness |
| POST | `/tools/hdp-components/install` | Install/register the component for the chosen strategy |
| GET | `/tools/hdp-components/installations` | List recent installation records |
| GET | `/tools/hdp-components/installations/<installation_id>` | Read one installation record |
| POST | `/tools/hdp-components/installations/<installation_id>/test` | Run the strategy-specific smoke test |

Catalog query parameters:
- `install_strategy`: `local_container` or `hpc_sif`; defaults to `hpc_sif`.
- `strategy`: compatibility alias for `install_strategy`.
- `source`: `local`, `remote`, or `all`; defaults to `all`. Remote entries are returned only when `WEBHDP_COMPONENT_INDEX_SOURCES` is configured.

Validation/install payload fields:
- `manifest` or `manifest_text`: required component manifest.
- `install_strategy`: `local_container` or `hpc_sif`; defaults to `hpc_sif`.
- `container_image`: required for local Docker installs unless the selected profile already declares an image.
- `sif_source`: required for HPC SIF installs. Accepts absolute remote `.sif` paths or HTTPS `.sif` URLs.
- `catalog_ref`: optional selected catalog reference from a remote component index.
- `sif_sha256`: optional expected SIF checksum. Passed through to HPC-Link for checksum verification.
- `docker_digest`, `trust_level`, `git`, `release`, `zenodo`, `sbom_url`, and `provenance_url`: optional catalog provenance metadata persisted with the installation record.

Remote component indexes:
- Configure comma- or newline-separated HTTPS URLs or absolute local JSON paths in `WEBHDP_COMPONENT_INDEX_SOURCES`.
- Configure `WEBHDP_COMPONENT_INDEX_MIN_TRUST` as `unknown`, `experimental`, `community-reviewed`, or `trusted`; the default `unknown` allows unpublished local testing.
- Index files use schema `webhdp.component-index.v1`.
- Each entry describes a component version, manifest URL plus optional manifest SHA-256, Git tag/commit, provider-neutral release URL/tag/assets, Zenodo DOI/concept DOI, trust level, compatible WebHDP range, Docker image/digest, optional SIF source/checksum, and SBOM/provenance links.
- WebHDP verifies manifest SHA-256, enforces trust and compatibility policy, and requires HTTPS metadata links before exposing an indexed component as installable. The native component registry remains the runtime authority after installation.
- The formal schema is `docs/schemas/webhdp_component_index_v1.schema.json`; the local unpublished fixture is `docs/examples/component-index/index.json`.

Local Docker behavior:
- Validation checks Docker CLI reachability, image availability, and configured image policy.
- `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST` limits permitted image names using comma-separated glob patterns.
- `WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES=true` requires `@sha256:` image references.
- Smoke tests use `install.test`, mount fixture files into `/inputs`, write outputs under `/outputs`, set the WebHDP component request/response environment variables, and run with `--network none`.

HPC behavior:
- Validation asks HPC-Link to validate the SIF source and target runtime.
- Installation asks HPC-Link to install or verify the SIF, then registers the installed SIF path in the native component profile.
- Smoke tests use `hpc.test` and run through the HPC-Link component test endpoint.

## 6. Auth API (`/api/v1/auth`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/register` | No | Public | Request a registration link with an email address |
| POST | `/resend-verification` | No | Public | Request a fresh verification email |
| POST | `/verify-email` | No | Public | Confirm email ownership and set the account password |
| GET | `/verify-email/<token>` | No | Public | Retired path for old links, returns HTTP 410 |
| POST | `/login` | No | Public | Return a JWT or an optional MFA challenge |
| POST | `/login/verify-code` | No | Public | Complete sign-in with the emailed MFA code |
| POST | `/login/resend-code` | No | Public | Request a new login MFA code |
| POST | `/login/verify-recovery-code` | No | Public | Complete an active sign-in challenge with a recovery code |
| GET | `/me` | Yes | Any authenticated | Get current user profile |
| PUT | `/me` | Yes | Any authenticated | Update profile fields. The verified sign-in email is read-only |
| PUT | `/me/password` | Yes | Any authenticated | Change current user password |
| POST | `/logout` | Yes | Any authenticated | Revoke current token |
| GET | `/me/zenodo-credentials` | Yes | Any authenticated | List available named Zenodo keys, accepted shares, pending invitations, outgoing shares, and active selections |
| POST | `/me/zenodo-credentials` | Yes | Any authenticated | Create a named personal Zenodo key for Sandbox or Production |
| PATCH | `/me/zenodo-credentials/<credential_id>` | Yes | Owner only | Rename an owned Zenodo key |
| DELETE | `/me/zenodo-credentials/<credential_id>` | Yes | Owner only | Delete an owned Zenodo key and clear related active selections |
| POST | `/me/zenodo-credentials/<credential_id>/validate` | Yes | Owner or accepted recipient | Validate an accessible key with live read, draft create, and draft cleanup checks |
| POST | `/me/zenodo-credentials/<credential_id>/share` | Yes | Owner only | Invite another user by email/account to share access to an owned key |
| PUT | `/me/zenodo-active-credentials/<environment>` | Yes | Any authenticated | Set the user's active key for Sandbox or Production |
| POST | `/me/zenodo-credential-shares/<share_id>/accept` | Yes | Recipient only | Accept an incoming share invitation |
| POST | `/me/zenodo-credential-shares/<share_id>/decline` | Yes | Recipient only | Decline an incoming share invitation |
| DELETE | `/me/zenodo-credential-shares/<share_id>` | Yes | Owner only | Revoke an outgoing share invitation or accepted share |
| GET | `/me/zenodo-credentials/<environment>` | Yes | Any authenticated | Compatibility wrapper for masked personal credential state in one environment |
| PUT | `/me/zenodo-credentials/<environment>` | Yes | Any authenticated | Compatibility wrapper to save a personal credential for one environment |
| DELETE | `/me/zenodo-credentials/<environment>` | Yes | Any authenticated | Compatibility wrapper to delete a personal credential for one environment |
| POST | `/me/zenodo-credentials/<environment>/validate` | Yes | Any authenticated | Compatibility wrapper to validate the stored personal credential for one environment |

### Email-first account registration

Submit `{"email":"researcher@example.org"}` to `/register` or
`/resend-verification`. HTTP 202 returns `data.accepted: true` and a generic
inbox message. The same reply covers addresses that are already active or
inside the resend cooldown. An attempted SMTP delivery that fails produces
`VERIFICATION_EMAIL_UNAVAILABLE` with HTTP 503. A failed send preserves an
earlier valid registration link.

The emailed browser link opens `/verify-email` with the token in the URL
fragment. Submit `{"token":"<email-link-token>","password":"<chosen-password>"}`
to `POST /verify-email`. A successful request creates or activates the
account, consumes the challenge, and returns HTTP 200. Sign in with the
chosen password afterwards. Passwords for new accounts contain 8 to 128
characters. Expired, invalid, or consumed tokens return
`INVALID_EMAIL_VERIFICATION_LINK`. A successful resend retires earlier links.
The default link lifetime is 24 hours and the default resend cooldown is
60 seconds.

These identity endpoints accept JSON request bodies up to 16 KiB. Invalid
JSON or email fields return a validation error. Authentication throttling is
shared across API workers, and a rate-limit rejection returns HTTP 429 with
`retry_after_seconds` and `Retry-After`. A concurrent signup operation can
return `REGISTRATION_BUSY` with retry guidance. Request a new link for a
pending account created by an earlier release. Existing verified users retain
their sign-in credentials.

### Zenodo credentials

`<environment>` is `sandbox` or `production`.

Zenodo credential responses never include cleartext tokens. User and institution tokens are encrypted at rest; API clients receive names, environments, ownership/share metadata, active state, masked previews, and validation reports only. Sharing grants approved use of an encrypted credential record and does not reveal the token to the recipient or administrator.

New validation reports use `validation_mode: "live_write_cleanup"`. A successful report means WebHDP listed depositions, created a temporary draft deposition, and deleted that draft. Reports include capability rows for authentication, deposit read, draft create, and draft cleanup. Authentication or scope failures are reported as invalid; network, rate-limit, and server failures are reported as unreachable; cleanup failures are reported distinctly because a temporary draft may need manual review in Zenodo.

### Own account usage (`/api/v1/account/usage`)

`GET /api/v1/account/usage` returns the signed-in account's own resource usage. It requires an authenticated account and uses `Cache-Control: private, no-store`. Shared demonstration accounts use their separate demonstration allowance.

| Group | Fields |
|---|---|
| `uploads` | `used_bytes`, `limit_bytes`, `active`, `active_limit`, `request_limit_bytes`, `stream_bytes_last_24_hours`, `stream_limit_bytes` |
| `native_processing` | `queued`, `running`, `active`, `active_limit` |
| `model_publication` | `active`, `active_limit`, `accepted_last_24_hours`, `daily_limit`, `daily_reset_at`, `stored_bytes`, `storage_limit_bytes`, `retention_seconds` |

`daily_reset_at` is a Unix timestamp in seconds when the model run limit is reached. A `null` local upload limit indicates that the account is exempt from that limit. Source usage includes reservations for uploads in progress. A request to upload beyond the account source or cloud transfer limit returns `UPLOAD_STORAGE_QUOTA` or `UPLOAD_STREAM_QUOTA` with HTTP 413. `UPLOAD_CONCURRENCY_QUOTA` has HTTP 429. Account limit errors include `error.details.usage` when a usage snapshot is available.

Model publishing and tutorial runs share the account allowances. `MODEL_PUBLICATION_ACTIVE_QUOTA` and `MODEL_PUBLICATION_DAILY_QUOTA` return HTTP 429. The daily response includes `Retry-After`. `MODEL_PUBLICATION_STORAGE_QUOTA` returns HTTP 413 when the account's model workspace is full. Shared queue or storage exhaustion produces `MODEL_PUBLICATION_QUEUE_FULL` with HTTP 429 or `MODEL_PUBLICATION_STORAGE_FULL` with HTTP 507.

`NATIVE_PROCESSING_QUOTA` returns HTTP 429 from native pipeline and Playground execution when the initiating account reaches its combined queued and running limit. The legacy submission endpoint uses the same reservation and limit. The response includes the caller's current counts. Administrators have a `null` native account limit.

## 7. Setup API (`/api/v1/setup`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/status` | No | Public | Check whether first-run setup is complete |
| POST | `/check` | No | Public | Run setup-time Zenodo and renderer checks |
| POST | `/test-render` | No | Public | Run renderer smoke test |
| POST | `/create-admin` | No | Public first-run path | Create the initial admin account |
| POST | `/complete` | No | Public first-run path | Mark setup as completed |
| POST | `/reset` | Yes | Admin | Reset setup state |

## 8. Session and HDPC API (`/api/v1/sessions`)

### 7.1 Session Context and Governance

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Accessible sessions | List sessions available to the current user |
| GET | `/<session_id>` | Yes | Session view | Get session context and governance state |
| GET | `/<session_id>/audit-events` | Yes | Session manage | Paginated session audit log |
| GET | `/<session_id>/workspace` | Yes | Session manage | Get workspace governance settings and publishing context |
| PUT | `/<session_id>/workspace` | Yes | Session manage | Update workspace governance settings |
| GET | `/<session_id>/workflow-state` | Yes | Session view | Get workflow state, draft metadata, and file metadata map |
| PUT | `/<session_id>/workflow-state` | Yes | Session edit + mutable | Update workflow state |
| GET | `/local-msf` | Yes | Any authenticated | List MSF files from the configured local input root |

### 7.2 Ingestion, Recovery, and Upload Operations

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/directory` | Yes | Any authenticated | Start ZIP, directory, or local ingestion workflow |
| POST | `/directory/recover` | Yes | Any authenticated | Recover an in-flight ingestion context from `submit_token` |
| GET | `/tasks/<task_id>` | Yes | Any authenticated | Poll async ingestion task status |
| GET | `/upload-operations` | Yes | Accessible sessions | List upload/ingestion operations visible to the user |
| GET | `/upload-operations/<session_id>` | Yes | Session view | Detailed upload operation payload for one session |
| GET | `/<session_id>/progress` | Yes | Session view | Aggregate upload progress for DB-backed uploaded files |
| POST | `/<session_id>/resume` | Yes | Session edit + mutable | Requeue failed or pending uploaded files |
| POST | `/import-hdpc` | Yes | Any authenticated | Import an existing `.hdpc` into a new session |

Ingestion notes:
- Successful upload completion normalizes to `scanned`.
- Resume only restarts meaningful upload/scan work; it does not recreate placeholder record workers.

### 7.3 HDPC Downloads and Read Models

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/<session_id>/hdpc` | Yes | Session download policy | Download raw session `.hdpc` |
| GET | `/<session_id>/hdpc/shared` | Yes | Shared-export download policy | Download sanitized shared `.hdpc` export |
| GET | `/<session_id>/cloud-downloads` | Yes | Raw `.hdpc` download policy | List owner-only Cloud Storage downloads for uploaded source artifacts |
| GET | `/<session_id>/cloud-downloads/<mirror_id>` | Yes | Raw `.hdpc` download policy | Create a temporary provider download URL and redirect the owner |
| GET | `/<session_id>/project-summary` | Yes | Session view | Project info, scan settings, config, and published records |
| GET | `/<session_id>/published-records` | Yes | Session view | Published record list from `.hdpc` |
| GET | `/<session_id>/files` | Yes | Session view | Paginated source-file list with optional search |
| GET | `/<session_id>/files/<file_id>/hierarchy` | Yes | Session view | Source-file hierarchy rooted at one file |
| GET | `/<session_id>/nodes` | Yes | Session view | Full session file tree merged with WebHDP file statuses |
| GET | `/<session_id>/workspace-summary` | Yes | Session view | Combined session, workflow, provenance, and `.hdpc` workspace summary |
| GET | `/<session_id>/operations/summary` | Yes | Session view | Product-facing counts and actionable upload/publish operations |
| GET | `/<session_id>/zenodo/uploadable-files` | Yes | Session view | Candidate items that can become or extend Zenodo uploads |
| GET | `/<session_id>/zenodo/uploads-by-tab` | Yes | Session view | Filtered upload lists grouped by product tabs |
| GET | `/<session_id>/zenodo_metadata` | Yes | Session view | Download all stored `record_metadata_json` entries as JSON |

HDPC read-model notes:
- Record `version` is always emitted as a string.
- `version_rank` and `previous_record_id` are additive lineage/order fields.
- File responses can include `validation_report_json` alongside concise `error_message`.
- Shared `.hdpc` download is a sanitized institution-sharing export, not the raw owner-only session database.
- Cloud download entries cover newly uploaded browser artifacts only: single source files, batch ZIP archives, and uploaded MSF files. Local/HPC and `server_only` sessions return an explicit unavailable reason instead of mirror items.

Cloud download list response:
```json
{
  "success": true,
  "data": {
    "session_id": 123,
    "available": true,
    "reason": null,
    "items": [
      {
        "id": 42,
        "artifact_kind": "batch_zip",
        "label": "Batch ZIP",
        "original_filename": "dataset.zip",
        "storage_provider": "dropbox",
        "status": "available",
        "can_download": true,
        "availability_status": "available",
        "availability_message": "Dropbox mirror is available"
      }
    ]
  }
}
```

`GET /<session_id>/cloud-downloads/<mirror_id>` returns `302` to a temporary provider URL. Pass `?as_json=true` to receive the generated `download_url` in JSON for frontend-controlled navigation. The endpoint rechecks provider availability, requires owner-equivalent raw download permission, and records a `cloud_mirror_downloaded` audit event.

### 7.4 Record Exploration, Traceability, and Versioning

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/<session_id>/records` | Yes | Session view | Session record explorer with provenance summary |
| GET | `/<session_id>/records/<local_record_id>` | Yes | Session view | Detailed single-record payload |
| GET | `/<session_id>/records/<local_record_id>/files` | Yes | Session view | Files attached to a local record |
| GET | `/<session_id>/records/<local_record_id>/traceability` | Yes | Session view | Record, source file, links, snapshots, and summary |
| GET | `/<session_id>/records/<local_record_id>/lineage` | Yes | Session view | Traceability plus source hierarchy and version lineage |
| GET | `/<session_id>/records/<local_record_id>/zenodo-status` | Yes | Session view | Draft/published/upload/community/actionable Zenodo state |
| POST | `/<session_id>/records/<local_record_id>/discard-draft` | Yes | Session edit + mutable | Discard a remote/local draft and restore prepared state |
| POST | `/<session_id>/records/<local_record_id>/create-version` | Yes | Session edit + mutable | Create a new local/remote Zenodo version from matched files |
| POST | `/<session_id>/versioning/match-files` | Yes | Session edit + mutable | Match a filesystem directory against published concepts by filename or hash |
| GET | `/<session_id>/concepts/<concept_rec_id>/latest-files` | Yes | Session view | Files belonging to the latest published version of a concept |
| GET | `/<session_id>/record-resolution` | Yes | Session view | Read saved batch record-resolution analysis and decisions |
| POST | `/<session_id>/record-resolution/analyze` | Yes | Session edit + mutable | Recompute batch record-resolution analysis using the active policy |
| PUT | `/<session_id>/record-resolution` | Yes | Session edit + mutable | Save batch record-resolution decisions before submit |

Record explorer notes:
- `/records` surfaces canonical submit-flow records only.
- Noncanonical legacy/manual rows and hidden placeholder duplicates are excluded from the main record inventory.
- Record-resolution analysis can include global hash collision warnings. These warnings are generated from accessible `.hdpc` `source_files.sha256_hash` values and include visible matching Zenodo records with `record_link` values where available.

### 7.5 Session Analytics and Cross-Session Exploration

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/<session_id>/provenance-report` | Yes | Session view | Session-level mapping and pipeline lineage analytics |
| GET | `/records/explorer` | Yes | User or moderator/admin | Cross-session record explorer with filtering and degraded-source warnings |

### 7.6 Native Session Batch Operations

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/<session_id>/batch-operations` | Yes | Session edit + mutable | Queue native batch actions such as draft creation, upload, publish, remove |
| GET | `/<session_id>/batch-operations` | Yes | Session view | List recorded native batch tasks for the session |
| GET | `/<session_id>/batch-operations/<task_id>` | Yes | Session view | Poll a native batch task including stored history fallback |

## 9. Upload Streaming API (`/api/v1/upload`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/stream` | Yes | Any authenticated | Stream a file directly to the configured cloud storage backend |

Headers used by `/stream`:
- `X-File-Name` required
- `Content-Length` recommended

## 10. Metadata API (`/api/v1/metadata`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST, PUT | `/file/<file_id>` | Yes | Any authenticated | Save or update file metadata |
| GET | `/file/<file_id>` | Yes | Any authenticated | Get file metadata |
| POST, PUT | `/user/<session_id>` | Yes | Any authenticated | Save validated session metadata |
| POST, PUT | `/user/<session_id>/draft` | Yes | Any authenticated | Save lenient metadata draft |
| GET | `/user/<session_id>` | Yes | Any authenticated | Get saved session metadata |
| POST, PUT | `/session/<session_id>/batch-update` | Yes | Any authenticated | Bulk-update batch metadata for files |
| POST | `/test-mapping` | Yes | Any authenticated | Run Zenodo payload mapping test |
| GET | `/workflow-support` | Yes | Any authenticated | Return the current metadata workflow contract |
| GET | `/zenodo-community-override` | Yes | Any authenticated | Return the effective global Zenodo community override |
| GET | `/schema` | No | Public | Return metadata schema JSON |

## 11. MSF API (`/api/v1/msf`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/upload` | Yes | Any authenticated | Upload MSF file |
| POST | `/parse` | Yes | Any authenticated | Parse MSF and return preview/profile |
| POST | `/validate` | Yes | Any authenticated | Validate MSF against file set |
| POST | `/detect-filename-column` | Yes | Any authenticated | Suggest filename column |
| GET | `/default-mapping` | Yes | Any authenticated | Get default MSF-to-Zenodo mapping |
| POST | `/metadata-for-files` | Yes | Any authenticated | Resolve file-level metadata from MSF |
| POST | `/patch` | Yes | Any authenticated | Apply MSF patch/repair workflow |
| POST | `/workflow/session/<session_id>/analyze` | Yes | Any authenticated | Analyze MSF against an existing session |
| POST | `/workflow/local/prepare` | Yes | Any authenticated | Prepare local-mode MSF workflow context |
| POST | `/workflow/session/<session_id>/start-local-scan` | Yes | Any authenticated | Start local-mode scan from analyzed MSF context |
| GET | `/tools/local/context` | Yes | Any authenticated | Local MSF tooling context |
| POST | `/tools/local/validate` | Yes | Any authenticated | Run local MSF validation helper |
| POST | `/tools/local/export` | Yes | Any authenticated | Export local MSF-derived output |

## 12. Standards and Template APIs

### EDM (`/api/v1/edm`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/test-mapping` | Yes | Any authenticated | EDM mapping, rendering, and validation test |
| POST | `/msf-columns` | Yes | Any authenticated | Extract MSF columns for EDM tooling |
| POST | `/mapping/export` | Yes | Any authenticated | Export EDM mapping |
| POST | `/mapping/import` | Yes | Any authenticated | Import EDM mapping |

### IIIF (`/api/v1/iiif`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/test-mapping` | Yes | Any authenticated | IIIF manifest generation and validation test |

### METS (`/api/v1/mets`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/test-mapping` | Yes | Any authenticated | METS generation and validation test |

### Templates (`/api/v1/templates`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Any authenticated | List templates |
| POST | `/` | Yes | Admin | Create template |
| GET | `/<template_id>` | Yes | Any authenticated | Get template detail |
| PUT | `/<template_id>` | Yes | Admin | Update template |
| DELETE | `/<template_id>` | Yes | Admin | Delete template |
| POST | `/preview` | Yes | Any authenticated | Render template preview |
| POST | `/validate` | Yes | Any authenticated | Validate rendered template output |

## 13. Pipeline API

### 12.1 Compatibility Pipeline API (`/api/v1/pipelines`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Any authenticated | List pipelines |
| GET | `/<identifier>` | Yes | Any authenticated | Get pipeline definition and effective config |
| POST | `/<identifier>/execute_on_local_files` | Yes | Any authenticated | Execute a pipeline against local/session files |
| GET | `/executions/<execution_uuid>/status` | Yes | Any authenticated | Poll pipeline execution status |

### 12.2 Native Pipeline API (`/api/v2`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/pipelines/<identifier>/readiness` | Yes | Session edit + mutable | Check every selected source and saved requirement without creating records or contacting remote services |
| POST | `/pipelines/<identifier>/execute` | Yes | Session edit + mutable | Execute the native submit pipeline on selected files or existing records |
| GET | `/runs/<run_id>` | Yes | Session view | Poll a native pipeline run |
| GET | `/runs/<run_id>/recovery` | Yes | Session edit + mutable | Review failed/unfinished records and continuation blockers from saved checkpoints |
| POST | `/runs/<run_id>/cancel` | Yes | Session edit + mutable | Cancel an unstarted native run |
| GET | `/sessions/<session_id>/records/<record_id>/derivatives` | Yes | Session view | List verified geometric detail reports for this record |
| GET | `/sessions/<session_id>/records/<record_id>/derivatives/<step_run_id>/<level>` | Yes | Session view | Download a checksum-verified source or generated detail level |
| POST | `/playground/execute` | Yes | Session edit + mutable | Execute or queue a Playground run |
| GET | `/playground/runs/<run_id>` | Yes | Session view | Poll a Playground run |
| POST | `/playground/runs/<run_id>/cancel` | Yes | Session edit + mutable | Cancel an unstarted Playground run |

Execution notes:
- First submit uses `local_file_paths`.
- Record-based rerun/reprocess uses `record_ids`.
- Readiness accepts the same source selection and execution settings. HTTP 200 carries `ready`, actionable `blockers`, deferred `unverified` checks, counts, `pipeline_version`, and `readiness_token` when ready. Local success does not verify remote runtimes, credentials, or generated exports.
- Pass `readiness_token` and `expected_version` unchanged to execution. The token expires after one hour for a new request; changed sources or settings return HTTP 409 with `error.details.readiness_stale`. Local blockers return HTTP 400 with `error.details.readiness`. Compatibility callers without a token still receive mandatory execution checks.
- Native asynchronous submission accepts a UUID `request_id`. Retry an uncertain accepted request with the identical payload and ID to reconnect, including after token expiry. A queued worker uses its captured pipeline/metadata settings and rechecks source contents before creating records or drafts.
- Session-aware native execution carries resolved publishing context, including environment and credential source.
- Submit-time LOD generation uses explicit `required`, `optional`, or `disabled` policy. `required` failures block Zenodo upload for the affected record.
- Playground accepts `async_execution: true` with a stable UUID `request_id` and returns HTTP 202 with `data.playground_run`. Repeating the same request returns its persisted run. Changed payloads with the same ID return HTTP 409.
- Playground paths are session-scoped for every adapter. Its worker uses the pinned component version and profile, and rechecks session permissions and paths before execution.
- Run payloads expose `can_cancel` for queued work. A cancelled run has terminal status `failed` and `result.cancelled: true`; late worker delivery cannot restart it.

Readiness streaming:
- Add `?stream=1` to the readiness request for `application/x-ndjson`. Each newline terminates a complete JSON event. Progress events carry `type: "progress"`, `checked`, and `total`; the final event carries `type: "result"` and the public `report` object. Streaming errors carry `type: "error"` and a message.
- Accept the report only after the response completes successfully. A truncated response, a missing result, or any error event cannot authorize execution. Check readiness again after cancellation or a transport error.
- The check indexes one inventory snapshot for the request and still hashes every selected source and required artifact. It does not cache file validity across requests. Responses use `Cache-Control: no-store`.

Failed-run continuation:
- `GET /runs/<run_id>` returns `data.run`, including `session_id`, the pinned `pipeline_config`, `outcomes`, and `can_edit`. Outcomes distinguish processing from current publication state, with per-record issues, step results, and next actions. Private checkpoints and readiness state are omitted.
- The recovery response returns `data.record_ids`, `records` with eligibility/reasons, `pipeline_identifier`, `pipeline_version`, `session_id`, `is_sandbox`, `whole_batch`, `unregistered_sources`, and `unregistered_record_ids`. It tracks the original selection separately from metadata-resolved assets and reconciles a stopped worker from local state without contacting compute services.
- Send `resume_from_run_id` with those existing `record_ids`, the original session, pipeline and environment to both readiness and execution. Do not send new file paths or execution items. Readiness pins the original version even if a newer version is active. Use a new UUID `request_id` for the continuation and repeat it unchanged if its acknowledgement is lost.
- Completed steps are reused only when component/profile/settings, input bytes, output bytes, and dependency state remain verified. Current curator metadata remains authoritative. Changed or unavailable files invalidate reuse. Remote mutations use record-aware reconciliation and idempotency guards.
- Published records, unresolved Zenodo acknowledgements, and interrupted active HPC allocations block continuation. Arbitrary batch components require the complete original record group; incomplete registration blocks this mode. Record-scoped processing can continue saved IDs while remaining sources are reviewed separately in Files. Runs without checkpoints require an ordinary reviewed record rerun.

Geometric derivative review:
- Reports are available for successful `geometric_lod_generator` steps with saved checkpoint hashes. The list returns `data.sets`, each with source/high/medium/low counts, sizes, hashes, geometry checks, and retained-mesh counts. An unavailable or altered report carries a per-set error. Older runs need regeneration to establish the hashes.
- Download `<level>` as `source`, `high`, `medium`, or `low`. A valid response is a GLB with `X-Content-SHA256` and `Cache-Control: no-store`. Verify bytes and checksum against the selected report before viewing. HTTP 409 means the saved model/report is unavailable or changed; HTTP 404 means the record/step/level combination was not found.
- Models and reports must resolve inside the authorized session. The source is the input supplied to that step, which may itself be an earlier derivative. Triangle reduction and byte reduction are reported separately; appearance still requires visual review.
- Browser checksum verification requires HTTPS or localhost. The comparison explains this requirement and leaves models unloaded when the browser cannot verify them.

### Uncertain Zenodo operations

`POST /api/v1/sessions/<session_id>/records/<local_record_id>/reconcile` requires session edit permission and a mutable workspace. Record detail exposes `zenodo_status.unresolved_operations` and pauses record mutations while an acknowledgement remains uncertain.

- Use `{}` to check a known publication or draft ID without issuing another mutation.
- Use `{"deposition_id": "9001"}` to reconnect an unknown draft after checking the publishing account. The authenticated response must match the original draft metadata and must not be connected to another local record.
- Use `{"confirmed_not_created": true}` only after verifying in Zenodo that no draft was created. This confirmation is recorded before permitting another creation attempt.
- Use `{"confirmed_not_published": true}` only after reviewing a known draft. The service additionally requires an authenticated, unsubmitted draft and a missing public record before permitting another publication attempt.

The credential environment comes from the local record. An unresolved outcome returns `data.success: false`, `error_code: REMOTE_OUTCOME_UNCERTAIN`, and `reconciliation_required: true`. HTTP 202 from Zenodo is finalized locally only when its state confirms publication; recovery also checks the published-record endpoint. See the [Zenodo API documentation](https://developers.zenodo.org/) for deposition states.

## 14. Submission API (`/api/v1/submissions`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Submission owner | List current user submissions |
| GET | `/<submission_id>` | Yes | Submission owner | Submission detail |
| GET | `/<submission_id>/progress` | Yes | Submission owner | Lightweight live progress payload |

### Guided 3D runs (`/api/v1/model-publication`)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/availability` | Signed-in account | Worker health, Sandbox credential readiness, and `practice_ready` for tutorial access |
| GET | `/queue` | Signed-in account | Aggregate worker and queue status |
| GET | `/samples` | Public | Built-in model packages with spreadsheet summaries |
| POST | `/jobs` | Signed-in account | Queue a direct model run and return `202`, or return the same run with `200` after an idempotent retry |
| GET | `/jobs` | Run owner | List recent runs, optionally filtered by `run_mode=practice` or `run_mode=sandbox` |
| GET | `/jobs/<job_id>` | Run owner | Get processing stage, mapped metadata, repair details and available results |
| GET | `/jobs/<job_id>/files/<filename>` | Run owner | Download a prepared file |

To practise, send form fields `run_mode=practice`, `sample_id=glazed-bowl`
or another built-in single model ID, and `metadata_source=archive` to `/jobs`.
A verified personal account can use this mode without a Sandbox credential. It
uses the normal CPU queue and returns `run_mode=practice` on the run. A finished
practice run offers `model.glb`, `preview.png`, `metadata.csv`, and
`metadata.json` for 48 hours and makes no external deposit. This mode rejects
custom uploads, metadata overrides and batch samples. Use a new
`Idempotency-Key` for a new run.

The default `run_mode=sandbox` requires an active Sandbox credential and
retains the existing model and metadata inputs. Shared demonstration accounts
continue to use their managed Sandbox credential and see only runs from their
current sign-in. Personal accounts can reopen their own runs after signing in
again.

## 15. Dataset API (`/api/v1/datasets`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Any authenticated | List visible dataset catalog |
| GET | `/conflict-review` | Yes | Moderator/Admin | Dataset duplicate/conflict review across visible sessions |
| GET | `/<dataset_key>/summary` | Yes | Visible dataset | Dataset summary |
| GET | `/<dataset_key>/duplicates` | Yes | Visible dataset | Duplicate groups for a dataset |
| POST | `/duplicate-check` | Yes | Any authenticated | Run duplicate check for prepared session files or explicit candidates |
| POST | `/<dataset_key>/export` | Yes | Visible dataset | Return dataset export bundle as JSON/CSV payloads |

## 16. Institution API (`/api/v1/institutions`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Any authenticated | List the caller's workspaces. Site administrators and moderators can request the institution inventory with `all=true` |
| POST | `/` | Yes | Site administrator | Create an official workspace |
| GET | `/suggestions` | Yes | Any authenticated | Find visible institution labels for profile affiliation |
| POST | `/affiliation` | Yes | Any authenticated | Save an affiliation label or select a visible institution |
| GET | `/workspace-requests` | Yes | Verified requester or site administrator | List the caller's requests. Administrators can request all pending or reviewed requests |
| POST | `/workspace-requests` | Yes | Verified account | Submit a new workspace for review |
| PATCH | `/workspace-requests/<request_id>/decision` | Yes | Site administrator | Approve or reject a pending request |
| GET | `/<institution_id>` | Yes | Institution member or site administrator | Get institution detail |
| PUT | `/<institution_id>` | Yes | Institution manager or site administrator | Update working settings. Only site administrators can change the official name |
| GET | `/<institution_id>/memberships` | Yes | Institution member or site administrator | List memberships with profile-aware member fields |
| POST | `/<institution_id>/memberships` | Yes | Institution manager or site administrator | Retired direct grant, returns HTTP 409 with `INSTITUTION_INVITATION_REQUIRED` |
| PUT | `/<institution_id>/memberships/<member_user_id>` | Yes | Institution manager or site administrator | Change the role of an existing member |
| DELETE | `/<institution_id>/memberships/<member_user_id>` | Yes | Institution manager or site administrator | Remove membership |
| GET | `/<institution_id>/invitations` | Yes | Institution manager or site administrator | List scoped invitations and delivery state |
| POST | `/<institution_id>/invitations` | Yes | Institution manager or site administrator | Send an invitation or resend an outstanding one |
| DELETE | `/<institution_id>/invitations/<invitation_id>` | Yes | Institution manager or site administrator | Revoke an invitation using its UUID |
| POST | `/invitations/preview` | Yes | Verified recipient | Check an invitation and show the workspace and offered role |
| POST | `/invitations/accept` | Yes | Verified recipient | Consume an invitation and open the membership |
| GET | `/<institution_id>/audit-events` | Yes | Institution manager or site administrator | View paginated audit records within the caller's scope |
| GET | `/<institution_id>/communities` | Yes | Institution member | List institution-managed default communities |
| POST | `/<institution_id>/communities` | Yes | Institution manager | Create institution community |
| PUT | `/<institution_id>/communities/<community_id>` | Yes | Institution manager | Update institution community |
| DELETE | `/<institution_id>/communities/<community_id>` | Yes | Institution manager | Delete institution community |
| GET | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Get masked institution Zenodo credential state |
| PUT | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Save or replace institution Zenodo credential |
| DELETE | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Delete institution Zenodo credential |
| POST | `/<institution_id>/zenodo-credentials/<environment>/validate` | Yes | Institution manager | Validate stored institution Zenodo credential |

### Workspace requests and membership

Submit `{"name":"Institution name","reason":"Optional purpose"}` to
`POST /workspace-requests`. HTTP 201 returns `data.request` with status
`pending`. The requester can track `pending`, `approved`, and `rejected`
states through `GET /workspace-requests`. Administrators can add `all=true`,
and the list accepts `status`, `page`, and `per_page`. A decision uses
`{"decision":"approve","note":"Optional review note"}` or `"reject"` as the
decision value. Approval returns the institution ID and creates the initial
Owner membership for the requester.

Valid membership roles are `reader`, `curator`, `manager`, and `owner`.
Only an institution owner or site administrator can change Owner assignments,
and each institution must retain an owner. The roster limits profile fields
using the viewer's access and member visibility preferences. Workspace audit
records follow session visibility. An affiliation update changes the profile
label and can select a default for an existing membership.

### Invitations

Send `{"email":"researcher@example.org","role":"reader"}` to
`POST /<institution_id>/invitations`. HTTP 200 returns `data.invitation`
and `data.delivery`. A saved invitation with `delivery: "failed"` can be
retried. A successful resend for the same pending email replaces its link
after the cooldown. A failed resend preserves the previous valid link.
Invitations expire after seven days. The resend
cooldown is one minute and the institution delivery limit is 60 attempts per
rolling hour. Rate limits return HTTP 429 with `Retry-After`.

The management list accepts `offset` and `limit` and returns
`data.invitations` and `data.total`. An invitation row describes its role,
recipient, state, delivery result, and timing. Managers can manage invitations
for ordinary roles. Owner invitations are visible to institution owners and
site administrators.

The recipient submits `{"token":"<email-link-token>"}` to the preview or
accept endpoint. Preview returns the workspace, offered role, expiry, and
current role if the recipient already belongs to that workspace. Acceptance
atomically consumes the hash-matched invitation and returns the workspace,
membership role, and `already_member`. Existing roles remain in effect.
An expired, withdrawn, consumed, or otherwise unavailable token returns
`INVITATION_INVALID` with HTTP 404. A verified account with another
address returns `INVITATION_EMAIL_MISMATCH` with HTTP 403. A legacy address
ambiguity returns `EMAIL_IDENTITY_AMBIGUOUS` with HTTP 409. The token itself
is absent from API responses, the roster, and the audit log.

Institution credential responses are masked and never expose cleartext tokens. Validation uses the same `live_write_cleanup` mode as user credentials: read depositions, create a temporary draft, and delete the draft in cleanup.

## 17. Tools API (`/api/v1/tools`)

### 16.1 Context, Diagnostics, and Cleanup

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/context` | Yes | Any authenticated | Return tool visibility, workflow contract, and platform context |
| GET | `/hpc-diagnostics` | Yes | Admin | HPC/local deployment diagnostics |
| POST | `/session-cleanup/analyze` | Yes | Admin | Analyze removable stale sessions |
| POST | `/session-cleanup/execute` | Yes | Admin | Remove selected stale sessions |

### 16.2 Zenodo Batch Operations

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/zenodo-batch-operations/records` | Yes | Moderator/Admin | Filter eligible records for cross-session Zenodo operations |
| POST | `/zenodo-batch-operations/community-operations` | Yes | Moderator/Admin | Queue a Zenodo community batch action |
| GET | `/zenodo-batch-operations/history` | Yes | Moderator/Admin | List persisted batch-operation runs |
| GET | `/zenodo-batch-operations/tasks/<task_id>` | Yes | Moderator/Admin | Poll a Zenodo batch-operation task |

### 16.3 Zenodo Account Retrieval

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/zenodo-account-retrieval/context` | Yes | Any authenticated | List accessible Zenodo credentials plus retrieval defaults and rate-limit policy |
| POST | `/zenodo-account-retrieval/jobs` | Yes | Credential access | Queue account retrieval for the selected credential |
| GET | `/zenodo-account-retrieval/jobs` | Yes | Owner/Admin | List persisted retrieval jobs; admins may pass `all=true` |
| GET | `/zenodo-account-retrieval/jobs/<retrieval_id>` | Yes | Job owner/Admin | Return job status, progress, checkpoint summary, manifest, shards, and errors |
| GET | `/zenodo-account-retrieval/jobs/<retrieval_id>/records` | Yes | Job owner/Admin | Search records across generated retrieval shards |
| POST | `/zenodo-account-retrieval/jobs/<retrieval_id>/pause` | Yes | Job owner/Admin | Request cooperative pause after the current page/window checkpoint |
| POST | `/zenodo-account-retrieval/jobs/<retrieval_id>/resume` | Yes | Job owner/Admin + credential access | Requeue the same retrieval ID and continue from checkpoint |
| POST | `/zenodo-account-retrieval/jobs/<retrieval_id>/cancel` | Yes | Job owner/Admin | Request cooperative cancellation |
| POST | `/zenodo-account-retrieval/jobs/<retrieval_id>/compact` | Yes | Job owner/Admin | Create compacted retrieval shard sessions from the collection |
| DELETE | `/zenodo-account-retrieval/jobs/<retrieval_id>/compacted-shards` | Yes | Job owner/Admin | Delete compacted shard sessions while leaving the retrieval collection history |
| PATCH | `/zenodo-account-retrieval/jobs/<retrieval_id>/retention` | Yes | Job owner/Admin | Store retention choices for original and compacted shards |
| PATCH | `/zenodo-account-retrieval/jobs/<retrieval_id>/schedule` | Yes | Job owner/Admin | Store an incremental schedule for a completed collection |
| POST | `/zenodo-account-retrieval/jobs/<retrieval_id>/schedule/run-now` | Yes | Job owner/Admin + credential access | Queue an incremental child retrieval immediately from the parent collection |
| GET | `/zenodo-account-retrieval/jobs/<retrieval_id>/export/<format>` | Yes | Job owner/Admin | Export `manifest`, `csv`, or `archive` for a retrieval collection |
| DELETE | `/zenodo-account-retrieval/jobs/<retrieval_id>` | Yes | Job owner/Admin | Explicitly delete generated shard sessions/files and the job history entry |

`POST /zenodo-account-retrieval/jobs` accepts:
- `credential_id` (required): named Zenodo credential visible to the requester
- `max_records` (optional): positive integer limit, maximum `1,000,000`; omit for all accessible records
- `start_datetime` / `start_date` (optional): inclusive lower created-date bound
- `end_datetime` / `end_date` (optional): inclusive upper created-date bound
- `sync_mode` (optional): `full` or `incremental`; `incremental: true` is also accepted
- `parent_retrieval_id` (optional): completed parent collection for incremental mode; if omitted, WebHDP selects the latest successful collection for the same credential/environment visible to the requester
- `incremental_overlap_hours` (optional): `0` to `168`, default `24`; subtracted from the parent collection's latest retrieved record timestamp

Retrieval jobs use authenticated Zenodo deposition listing for published records and drafts, `all_versions=1`, `size=100`, and adaptive date-window splitting. Responses never include cleartext tokens. Public checkpoint payloads expose `seen_count`, not the full internal dedupe set.

When Zenodo rejects a dense page-boundary request with `400`/`422`, the runner treats the response as a split signal and retries smaller windows. Resume keeps the same `retrieval_id`, manifest, generated shards, pending windows, and dedupe state.

Generated sessions are completed explorer-only sessions with `origin_type="zenodo_deep_retrieval"` and `access_mode="explorer_only"`. Their `.hdpc` records use `record_origin="zenodo_retrieval"` and snapshot stage `account_retrieval_deposition`. Completed jobs also expose collection metadata: latest created/modified record timestamps, throughput, duplicate-skipped counts, stale heartbeat state, sync mode, parent retrieval ID, retention policy, compaction metadata, and schedule settings.

`GET /zenodo-account-retrieval/jobs/<retrieval_id>/records` accepts `q`, `status`, `capability`, `limit`, and `offset` query parameters. `POST /compact` accepts `target_records_per_shard`, defaulting to `5,000`. `PATCH /retention` accepts `keep_original_shards`, `keep_compacted_shards`, and `notes`. `PATCH /schedule` accepts `enabled`, `frequency` (`daily`, `weekly`, or `monthly`), `incremental_overlap_hours`, and optional `max_records`. The schedule runner task is `execute_due_zenodo_account_retrieval_schedules`.

Detailed behavior: `../guides/zenodo_account_retrieval.md`.

### 16.4 Community Moderation

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/community-moderation/requests` | Yes | Moderator/Admin | List moderation requests |
| POST | `/community-moderation/actions` | Yes | Moderator/Admin | Queue moderation action |
| GET | `/community-moderation/history` | Yes | Moderator/Admin | List moderation action history |
| GET | `/community-moderation/tasks/<task_id>` | Yes | Moderator/Admin | Poll moderation task status |

### 16.5 Local Admin Workflow Tools

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| POST | `/pipeline-preflight/local` | Yes | Admin+Local | Validate local MSF, service readiness, and pipeline blockers |
| POST | `/metadata-normalizer/local` | Yes | Admin+Local | Run local metadata normalization helper |
| POST | `/output-preview/local` | Yes | Admin+Local | Generate local EDM/IIIF/METS preview outputs |

## 18. Admin API (`/api/v1/admin`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/submissions` | Yes | Moderator/Admin | List submissions across users |
| GET | `/submissions/<submission_id>` | Yes | Moderator/Admin | Submission detail with review history |
| POST | `/submissions/<submission_id>/review` | Yes | Moderator/Admin | Add moderation review/status |
| DELETE | `/submissions/<submission_id>` | Yes | Admin | Delete submission |
| GET | `/upload-operations` | Yes | Moderator/Admin | List upload operations across users |
| GET | `/stats` | Yes | Admin | Admin dashboard statistics |
| GET | `/users` | Yes | Admin | List users |
| PUT | `/users/<user_id>/role` | Yes | Admin | Update user role |
| PUT | `/users/<user_id>/capabilities` | Yes | Admin | Update user capability list |
| POST | `/users/<user_id>/hdpc/import` | Yes | Admin | Import `.hdpc` for another user |
| GET | `/zenodo-community-config` | Yes | Admin | Get global forced Zenodo community config |
| POST | `/zenodo-community-config` | Yes | Admin | Update global forced Zenodo community config |
| GET | `/pipelines/<pipeline_id>/config` | Yes | Admin | Get persisted pipeline config |
| POST | `/pipelines/<pipeline_id>/config` | Yes | Admin | Update pipeline config |
| GET | `/pipelines/render/status` | Yes | Admin | Renderer service status |
| POST | `/pipelines/render/test` | Yes | Admin | Renderer smoke test |
| POST | `/pipelines/converter/test` | Yes | Admin | Converter smoke test |
| POST | `/edm-config` | Yes | Admin | Update EDM configuration |
| GET | `/edm-validator/status` | Yes | Admin | Local EDM validator enabled state, endpoint, health, and version/source metadata |
| GET | `/storage-config` | Yes | Admin | Read storage configuration |
| POST | `/storage-config` | Yes | Admin | Update storage configuration |
| GET | `/modality-config` | Yes | Admin | Read modality configuration |
| POST | `/modality-config` | Yes | Admin | Update modality configuration |
| DELETE | `/modality-config` | Yes | Admin | Reset modality configuration |
| GET | `/version-detection-config` | Yes | Admin | Read default record-resolution and hash collision policy |
| POST | `/version-detection-config` | Yes | Admin | Update default record-resolution and hash collision policy |
| GET | `/storage-status` | Yes | Any authenticated | Return effective storage/provider status |
| GET | `/projects/media` | Yes | Admin | Serve admin media preview assets |
| GET | `/observability/credentials-status` | Yes | Admin | Masked credential state plus integration readiness |
| GET | `/observability/api-activity` | Yes | Admin | API activity feed and summary |
| POST | `/observability/checks/<check_id>` | Yes | Admin | Execute a targeted observability check |
| GET | `/version` | Yes | Admin | Backend version/build metadata |

Version detection config includes `hash_collision_policy`:

```json
{
  "hash_collision_policy": {
    "enabled": true,
    "min_size_bytes": 1048576,
    "excluded_extensions": [".csv", ".json", ".log", ".md", ".text", ".tsv", ".txt", ".xml"],
    "exclude_generated_renders": true
  }
}
```

When enabled, matching source-file hashes become warning candidates in batch record-resolution review. The warning is advisory and does not block submit once the user saves an explicit decision.

### 17.1 Local EDM Validator Status

`GET /api/v1/admin/edm-validator/status`

Returns the configured local EDM validator endpoint, whether validation is enabled or required, whether it continues after errors, health details from `/actuator/health`, and build and source metadata from `/actuator/info`. The `info.summary` response includes schema versions reported by the validator when available.

Example response:

```json
{
  "success": true,
  "data": {
    "enabled": true,
    "required": true,
    "url": "http://local-edm-validator:8080",
    "continue_on_error": true,
    "health": {
      "ok": true,
      "status_code": 200,
      "status": "UP",
      "url": "http://local-edm-validator:8080/actuator/health",
      "response_time_millis": 18,
      "details": {
        "status": "UP"
      }
    },
    "info": {
      "ok": true,
      "status_code": 200,
      "url": "http://local-edm-validator:8080/actuator/info",
      "response_time_millis": 12,
      "summary": {
        "title": "Local EDM Validator",
        "version": "1.0.0-local",
        "repository": "https://github.com/Digital-Humanities-Jena/local-edm-validator",
        "source_ref": "a7b3ad4",
        "image_tag": "local-edm-validator:local",
        "git_branch": "main",
        "git_commit_short": "a7b3ad4",
        "build_time": "2026-04-30T10:58:46.055Z",
        "edm_schema_version": "20260720",
        "metis_schema_version": "15"
      }
    }
  }
}
```

Operators should use this endpoint as the API equivalent of the Settings -> EDM Config status card.

## 19. Admin Cloud Connectivity API (`/api/v1/admin/cloud`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/test/gdrive` | Yes | Admin | Test Google Drive connectivity |
| GET | `/test/dropbox` | Yes | Admin | Test Dropbox connectivity |

## 20. HPC Allocations and Reserved GPUs (`/api/v1/hpc-link`)

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/status` | Authenticated account | Read allocation availability, the caller’s quota, and session status |
| GET | `/allocations` | Authenticated account | List the caller’s current allocation requests |
| POST | `/allocations` | Verified account with HPC Access, or an authorized operator | Request resources for an owned session |
| GET | `/reservations` | Verified account with HPC Access; explicit grant | List reservations granted to the account |
| POST | `/reservations/<reservation_id>/claim` | Same; owner of the specified session | Claim a reservation and return its ordinary allocation handle |
| GET | `/allocations/<allocation_id>` | Allocation access | Poll the claim and live scheduler status |
| POST | `/allocations/<allocation_id>/preflight` | Current compute access | Check components and resources on a running allocation |
| POST | `/allocations/<allocation_id>/stage/cloud-references` | Current compute access | Stage cloud files using the caller's upload receipts |
| POST | `/allocations/<allocation_id>/release` | Allocation owner or administrator | Cancel a request or release idle resources |

Use `session_id` and `purpose` on `/status` to see the relevant request. The
`available` flag means HPC-Link is configured and enabled. The `active_hpc_allocation`
flag requires a running allocation with an unexpired deadline when one is known.
`active_hpc_gpu_count` is the GPU count of that usable allocation, when present.
A value of `0` means the running allocation is CPU-only.
For the caller's own allocation, `gpu_allocation_status` distinguishes a request
queued in WebHDP, a request awaiting scheduler assignment (`allocating`), a
running allocation, or a terminal state such as `failed` or `expired`.
`gpu_allocation_id`, `gpu_allocation_gpu_count`, and `gpu_allocation_scheduler_reason`
report the recorded request, when present. Poll that ID for scheduler updates.
Cluster capacity and start time remain unknown until the scheduler responds.
The `quota` object reports the caller’s `active`, `active_limit`, `queued`,
`queued_limit`, `max_gpu_count`, and `max_duration_minutes`. Active includes
pending scheduler requests and reservation claims. Queued requests count
towards the waiting limit until they start, expire, or are cancelled. A full
queue or excessive resource request returns `HPC_QUOTA_EXCEEDED` with HTTP 429.
GPU counts are whole numbers from zero to the configured maximum; a zero count
requests CPU resources. Walltime requests begin at five minutes. The gateway and
Slurm can impose tighter limits.

The caller can only list, inspect or release their own allocations through the
regular workflow interface. Normal responses omit gateway credentials, internal
paths and raw diagnostics. An authorized editor can use a shared session's
ordinary ready allocation through its pipeline. Its owner retains control of the
allocation handle. A reserved GPU claim remains exclusive to its grantee.
Normal owners can still cancel their queued work or release idle resources after
their HPC grant is removed. Release waits until active processing has finished.

For a claim supply integer `session_id` and `purpose` of `workflow` or
`playground`. Use the WebHDP reservation ID, which is distinct from the gateway
registration ID and the scheduler job ID. Only one active claim per reservation
is allowed. A repeat claim for the same session/account returns the existing
allocation. The claim uses the existing global and user allocation limits.
A release for an operator-held GPU detaches access without cancelling Slurm.

Administrators register and edit WebHDP grants:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/admin/hpc-reservations` | List WebHDP registrations |
| POST | `/api/v1/admin/hpc-reservations` | Register an available gateway reservation; supply `gateway_reservation_id`, `label` and `allowed_emails` |
| PATCH | `/api/v1/admin/hpc-reservations/<reservation_id>` | Change `label`, `enabled` or `allowed_emails`; release an active claim before removing its grant |

See the [demo runbook](../guides/prereserved_gpu_demo.md) for the separate,
private HPC-Link registration and staging/rehearsal steps.

## 21. WebHDP-Link API (`/api/v1/link`)

The [Link OpenAPI contract](webhdp-link.openapi.json), also served at
`/api/v1/link/openapi.json`, describes all request and response schemas.
`GET /api/v1/link/discovery` is public. It supplies the issuer, endpoints and
supported scopes. Link returns direct JSON responses and
`application/problem+json` errors. It does not use the native response
envelope above.

| Route family | Access |
|---|---|
| `/oauth/request`, `/oauth/token`, `/oauth/revoke` | Registered client flow; authorization code exchange requires S256 PKCE |
| `/oauth/authorize`, `/grants`, `/jobs` | Verified user with WebHDP JWT; user-owned consent and job views |
| `/admin/*` | WebHDP administrator JWT |
| `/pipelines`, `/uploads`, `/runs` | Scoped Link bearer token and approved application/publication; browser origin must match authorization |

Submit a run with an `Idempotency-Key` and a list of authorized upload IDs.
Retry uncertain submissions with the same key and inputs. A changed request
with the same key returns a conflict. A durable job can wait for resources
before a component starts. Check both `status` and `progress.phase`, and use
the artifact's SHA-256 and size to verify its download. A user's token expiry
does not cancel accepted work. Reconnect as the same user to recover it.
See the [integration guide](../guides/webhdp_link.md) for the browser SDK and
[API examples](webhdp_api_examples.md#16-use-webhdp-link-with-a-service-token)
for a server-side client.

## 22. Async and Degraded-Source Notes

- Ingestion returns async task IDs via `/sessions/directory`; poll `/sessions/tasks/<task_id>`.
- Native session batch operations and moderator tool tasks have dedicated task-status routes.
- Some record and explorer endpoints can return `source_state: "hdpc_unavailable"` or `503 SOURCE_UNAVAILABLE` when the session `.hdpc` is not present on the current backend instance.
- Shared `.hdpc` exports are sanitized allowlist copies intended for institution-safe exploration, not raw writable project replicas.

## 23. Related References

- Practical examples: `webhdp_api_examples.md`
- `.hdpc` schema: `../architecture/hdpc_schema.md`
- System architecture: `../architecture/system_architecture.md`
- Troubleshooting: `../guides/troubleshooting.md`
