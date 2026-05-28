# WebHDP API Reference

Base URLs, default development environment:
- `http://localhost:5000/api/v1`
- `http://localhost:5000/api/v2`

This document describes the WebHDP HTTP API currently registered under `/api/v1/...` and `/api/v2/...`.
It was reconciled against the live Flask route map on April 29, 2026.

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

- JWT bearer authentication is required for all protected routes.
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
| POST | `/register` | No | Public | Register a user |
| GET | `/verify-email/<token>` | No | Public | Verify email token |
| POST | `/login` | No | Public | Authenticate and return JWT |
| GET | `/me` | Yes | Any authenticated | Get current user profile |
| PUT | `/me` | Yes | Any authenticated | Update current user email |
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

`<environment>` is `sandbox` or `production`.

Zenodo credential responses never include cleartext tokens. User and institution tokens are encrypted at rest; API clients receive names, environments, ownership/share metadata, active state, masked previews, and validation reports only. Sharing grants approved use of an encrypted credential record and does not reveal the token to the recipient or administrator.

New validation reports use `validation_mode: "live_write_cleanup"`. A successful report means WebHDP listed depositions, created a temporary draft deposition, and deleted that draft. Reports include capability rows for authentication, deposit read, draft create, and draft cleanup. Authentication or scope failures are reported as invalid; network, rate-limit, and server failures are reported as unreachable; cleanup failures are reported distinctly because a temporary draft may need manual review in Zenodo.

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
| POST | `/pipelines/<identifier>/execute` | Yes | Session edit + mutable | Execute the native submit pipeline on selected files or existing records |
| GET | `/runs/<run_id>` | Yes | Any authenticated | Poll a native pipeline run |
| POST | `/playground/execute` | Yes | Any authenticated | Execute a playground run |
| GET | `/playground/runs/<run_id>` | Yes | Any authenticated | Poll a playground run |

Execution notes:
- First submit uses `local_file_paths`.
- Record-based rerun/reprocess uses `record_ids`.
- Session-aware native execution carries resolved publishing context, including environment and credential source.
- Submit-time LOD generation uses explicit `required`, `optional`, or `disabled` policy. `required` failures block Zenodo upload for the affected record.

## 14. Submission API (`/api/v1/submissions`)

| Method | Path | Auth | Access | Purpose |
|---|---|---|---|---|
| GET | `/` | Yes | Submission owner | List current user submissions |
| GET | `/<submission_id>` | Yes | Submission owner | Submission detail |
| GET | `/<submission_id>/progress` | Yes | Submission owner | Lightweight live progress payload |

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
| GET | `/` | Yes | Any authenticated | List institutions visible to the user |
| POST | `/` | Yes | Any authenticated | Create institution |
| GET | `/<institution_id>` | Yes | Institution member | Get institution detail |
| PUT | `/<institution_id>` | Yes | Institution manager | Update institution |
| GET | `/<institution_id>/memberships` | Yes | Institution member | List memberships |
| POST | `/<institution_id>/memberships` | Yes | Institution manager | Add membership |
| PUT | `/<institution_id>/memberships/<member_user_id>` | Yes | Institution manager | Update membership role |
| DELETE | `/<institution_id>/memberships/<member_user_id>` | Yes | Institution manager | Remove membership |
| GET | `/<institution_id>/audit-events` | Yes | Institution member | Paginated institution audit log |
| GET | `/<institution_id>/communities` | Yes | Institution member | List institution-managed default communities |
| POST | `/<institution_id>/communities` | Yes | Institution manager | Create institution community |
| PUT | `/<institution_id>/communities/<community_id>` | Yes | Institution manager | Update institution community |
| DELETE | `/<institution_id>/communities/<community_id>` | Yes | Institution manager | Delete institution community |
| GET | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Get masked institution Zenodo credential state |
| PUT | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Save or replace institution Zenodo credential |
| DELETE | `/<institution_id>/zenodo-credentials/<environment>` | Yes | Institution manager | Delete institution Zenodo credential |
| POST | `/<institution_id>/zenodo-credentials/<environment>/validate` | Yes | Institution manager | Validate stored institution Zenodo credential |

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

Returns the configured local EDM validator endpoint, whether validation is enabled, whether validation continues after errors, health details from `/actuator/health`, and build/source metadata from `/actuator/info`.

Example response:

```json
{
  "success": true,
  "data": {
    "enabled": true,
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
        "source_ref": "b1ba678",
        "image_tag": "local-edm-validator:local",
        "git_branch": "main",
        "git_commit_short": "b1ba678",
        "build_time": "2026-04-30T10:58:46.055Z"
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

## 20. Async and Degraded-Source Notes

- Ingestion returns async task IDs via `/sessions/directory`; poll `/sessions/tasks/<task_id>`.
- Native session batch operations and moderator tool tasks have dedicated task-status routes.
- Some record and explorer endpoints can return `source_state: "hdpc_unavailable"` or `503 SOURCE_UNAVAILABLE` when the session `.hdpc` is not present on the current backend instance.
- Shared `.hdpc` exports are sanitized allowlist copies intended for institution-safe exploration, not raw writable project replicas.

## 21. Related References

- Practical examples: `webhdp_api_examples.md`
- `.hdpc` schema: `../architecture/hdpc_schema.md`
- System architecture: `../architecture/system_architecture.md`
- Troubleshooting: `../guides/troubleshooting.md`
