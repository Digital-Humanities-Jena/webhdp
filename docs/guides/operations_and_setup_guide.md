# Operations and Setup Guide

This guide is for administrators and operators preparing WebHDP for production or a public scientific demonstration.

For an existing deployment, start with the [alpha.4 upgrade checklist](upgrade_alpha4.md).
For a public presentation, use the [pre-reserved GPU runbook](prereserved_gpu_demo.md).
For external applications, use the separate [WebHDP-Link deployment runbook](webhdp_link_deployment.md).

## 1. Deployment Modes
Use one of the compose profiles depending on resource budget:
- Standard: `docker-compose.yml`
- Dev override: `docker-compose.dev.yml`
- HPC override: `docker-compose.hpc.yml`
- Linux HPC unlimited: `docker-compose.linux-hpc.yml`
- Low-resource (renderer/USDZ disabled): `docker-compose.low-resource.yml`
- Optional managed EDM validator: `docker-compose.edm-validator.yml`

Reference: `../docker_deployment_guide.md`.

WebHDP distinguishes three runtime classes:
- `server`: default for VPS/simple Linux servers. Heavy HDP Components require HPC-Link or must be disabled.
- `workstation-local`: explicit opt-in for capable local machines using `WEBHDP_DEPLOYMENT_MODE=local`, `WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true`, `COMPOSE_PROFILES=local-hdp-components`, and a deliberate local component image policy such as `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST`.
- `hpc`: remote/co-located high-performance execution through HPC-Link or the Singularity/Slurm runbooks.

Do not enable workstation-local compute on a small public VPS merely because Docker can start the services. That mode is for machines where the operator accepts local Blender/conversion workload.

## 2. Minimum Environment Configuration
Start from `.env.example` and define at least:
- `FLASK_ENV`
- `SECRET_KEY`: at least 32 bytes in production for HS256 JWT signing
- `CREDENTIAL_ENCRYPTION_KEY`: separate persistent production secret
- `FRONTEND_URL`
- `PUBLIC_BASE_URL` if the public WebHDP origin differs from `FRONTEND_URL`
- `WEBHDP_SESSIONS_PATH`
- `ZENODO_SANDBOX_API_KEY` and/or `ZENODO_API_KEY`
- `LOCAL_EDM_VALIDATOR_URL` unless using the managed Compose overlay
- SMTP mail settings for production login MFA; local development can keep
  `MFA_DEVELOPMENT_CODE_DELIVERY=inline` while `FLASK_ENV=development`
- `ANY_TO_USDZ_PLATFORM=linux/amd64` for local/full-function Docker unless the
  Admin USDZ conversion test passes on a different platform
- Cloud credentials if cloud storage is used

User and institution Zenodo keys configured through the UI are stored encrypted and shown only as masked previews. Personal keys may be named, shared by invitation, accepted by recipients, and selected as the active Sandbox or Production key for uploads. Sharing grants use of the encrypted credential record; it does not expose the cleartext token.

### Registration and invitation delivery

Set `FRONTEND_URL` to the public HTTPS origin for links in verification and
invitation emails. Configure the mail host, sender, and TLS or SSL mode for
your provider. `MAIL_TIMEOUT` limits SMTP socket operations. Test registration,
resend, and an invitation using an operator-controlled mailbox before inviting
users. Check the institution’s spam and quarantine handling during that test.

The API workers share authentication throttling through
`auth-throttle.sqlite3` in the writable instance directory. Keep that directory
shared across API workers on the host. `AUTH_THROTTLE_DB_PATH` can point to a
different shared local file. The stored keys are hashes keyed with the
application secret. If the store is unavailable, the API temporarily rejects
the protected public authentication requests.

`AUTH_TRUSTED_PROXY_HOPS` defaults to zero for a directly reached API. Compose
defaults to one for a private API reached through its nginx frontend. When
another proxy also appends addresses in front of nginx, set the count to
match the deployed chain. Keep the API reachable only through that chain.

Registration and resend share a five-minute window and a default limit of ten
requests per email address. The default IP limit is four times the address limit
so people sharing an institutional network can register. Configure this policy
with `REGISTER_RATE_LIMIT_ATTEMPTS`, `AUTH_RATE_LIMIT_IP_MULTIPLIER`,
`AUTH_RATE_LIMIT_WINDOW_SECONDS`, and `AUTH_RATE_LIMIT_LOCKOUT_SECONDS`.

Archived legacy fallback details live in `hdp_server_integration_guide.md`, but they are not part of the standard deployment template.

### Important operational paths
- Session shared path (`SHARED_SESSION_PATH` in containers)
- Local mode input/output mounts (`LOCAL_INPUT_PATH`, `LOCAL_OUTPUT_PATH`)

## 3. First-Time Setup Procedure
1. Start services.
2. Open `/setup?setup_token=<generated_setup_token>` in the UI when using `SETUP_BOOTSTRAP_TOKEN`.
3. Run system checks.
4. Create initial admin account.
5. Complete setup flag.

The setup token is only for first-run bootstrap. After successful setup the UI
clears it from browser session storage and routes the operator to `/login`.
When the frontend and backend are on different origins, include the frontend
origin in `CORS_ORIGINS` so setup POST requests can pass browser preflight.
6. Log in as admin and configure storage + pipeline settings.

Why this sequence is required:
- It prevents users from entering workflows before critical dependencies and governance controls are validated.

## 4. Storage Configuration
Admin endpoint/UI can set:
- Primary and secondary storage providers
- `storage_mode` (`pure_cloud`, `cloud_backup`, `server_only`, `local`)
- Fallback policy

Operational guidance:
- Use `pure_cloud` when minimizing persistent server storage is mandatory.
- Use `cloud_backup` when dual durability is required.
- Use `server_only` in isolated/internal deployments.
- Use `local` only for intentional mounted-folder workflows: workstation-local folder scans or HPC-attached storage. Do not use it as the default for a small VPS.
- Direct Cloud Storage downloads for uploaded source artifacts are available only for new sessions with active `pure_cloud` or `cloud_backup` mirroring. `server_only` and `local`/HPC sessions intentionally report cloud download unavailable in the file review UI.

Detailed behavior: `../storage_modes_architecture.md`.

### Account upload allowances

Apply revision `e2f1a3b4c567` before starting the new API. It adds an upload admission table and reads older source usage from existing file records. New installations use the same default limits.

| Environment setting | Default | Scope |
|---|---:|---|
| `ACCOUNT_UPLOAD_STORAGE_BYTES` | 50 GiB | Source data attached to an ordinary account's sessions and source bytes reserved by current uploads. ZIP accounting uses the larger of its compressed and expanded size, plus the uploaded metadata spreadsheet. For cloud archives, WebHDP reserves the size from the signed receipt first and checks the archive's actual size before extracting it. |
| `ACCOUNT_UPLOAD_MAX_ACTIVE` | 3 | Ordinary account's receiving uploads and queued scans. |
| `ACCOUNT_UPLOAD_STREAM_DAILY_BYTES` | 50 GiB | Ordinary account's cloud transfer allowance over a rolling 24-hour window. |

Administrators are exempt from these per-account upload caps. The existing HTTP request size and provider limits still apply. Standalone spreadsheet tools use a private temporary workspace per account with a 16 MiB file limit and 64 MiB retained workspace limit. Scratch spreadsheets expire after 24 hours. Re-upload a spreadsheet to use it in the new workspace if it was staged before this upgrade.

These allowances measure admitted source data and cloud transfer. HPC allocation limits and generated artifacts have separate checks. Uploads that fail before they create a session release their reservations. Quota reporting can retain charges for sessions that still have source records.

## 5. Pipeline Configuration
Admins can:
- Retrieve and update pipeline step configuration
- Test renderer and converter services
- Enable/disable steps through config and feature flags

Runtime policy:
- In `workstation-local`, enabled renderer/USDZ steps use local compute containers when healthy.
- In `server`, enabled renderer/USDZ steps require HPC-Link; disable them for low-resource operation.
- In `hpc`, component execution is expected to run through the active allocation or HPC deployment stack.

Feature flags:
- `ENABLE_RENDERER`
- `ENABLE_USDZ_CONVERSION`
- `ENABLE_LOCAL_EDM_VALIDATION`
- `LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR`
- `LOCAL_EDM_VALIDATOR_SOURCE_REF`
- `LOCAL_EDM_VALIDATOR_IMAGE`

EDM validation:
- Use Settings -> EDM Config to confirm whether local-edm-validator is enabled and reachable.
- The status card also shows validator version, commit/source ref, build time, and image tag when `/actuator/info` is available.
- Generated `edm.xml` files are accompanied by persisted validation details in the local `.hdpc` metadata, and the native pipeline also writes `edm.validation.json` next to the generated XML for audit review.
- For managed Compose deployments, clone `Digital-Humanities-Jena/local-edm-validator` into `external_code/local-edm-validator`, export `LOCAL_EDM_VALIDATOR_SOURCE_REF="$(git -C external_code/local-edm-validator rev-parse --short HEAD)"`, and start WebHDP with `docker-compose.edm-validator.yml`.
- Full validator setup, smoke tests, API status payload, and troubleshooting are documented in `local_edm_validator.md`.

Why this matters:
- It allows graceful degradation for constrained infrastructure while preserving metadata/publication workflows.

### Current implementation note
- The operational baseline currently uses predefined/default pipeline IDs (`render`, `metadata_only`) provided by WebHDP integration defaults.
- This reflects current production behavior and should be considered when planning strict reproducibility across environments.

### Current platform direction
- Native component import, native pipeline execution, and native playground execution are the primary workflow model.
- Standalone HDP-Server deployment is not part of the standard operational baseline.

Reference: `hdp_server_integration_guide.md` and `planned_future_updates.md`.

## 6. Version Detection and Global Hash Collision Warnings
The Admin Dashboard includes a Version Detection Policy card for pre-batch record-resolution behavior. This policy controls whether users see advisory warnings before processing files that may already exist in Zenodo.

Global hash collision warnings are enabled by default. During batch record-resolution analysis, WebHDP compares each non-exempt candidate source file hash against accessible `.hdpc` inventories across known sessions. If a matching `source_files.sha256_hash` is found, the candidate is marked as a warning and the matching Zenodo records are shown with title, status, DOI, environment, session/local record IDs, and an `Open Zenodo` link.

Default global hash collision policy:
- `enabled`: `true`
- `min_size_bytes`: `1048576` (`1 MB`)
- `excluded_extensions`: `.csv`, `.json`, `.log`, `.md`, `.text`, `.tsv`, `.txt`, `.xml`
- `exclude_generated_renders`: `true`

Operational behavior:
- Files smaller than the threshold are ignored.
- Sidecar text, JSON, XML, CSV/TSV, Markdown, and log files are ignored by default.
- Generated renders, thumbnails, previews, derived outputs, and `fast_renderer` outputs are ignored when file metadata identifies them as generated artifacts.
- A collision is advisory. It does not block upload or submit by itself.
- Users must still resolve the affected candidate by selecting and saving an action, such as creating a fresh record, versioning where allowed, or skipping the candidate.
- Non-privileged users see the visible matches they are allowed to access plus a hidden-count warning when additional matches exist outside their scope.

Admin controls:
- Enable or disable global hash collision warnings.
- Set the primary exception threshold in bytes.
- Enable or disable generated-render exclusion.
- Edit the secondary exception extension list.
- Save or restore the policy through `/api/v1/admin/version-detection-config`.

## 7. Zenodo Account Retrieval Operations
The Tools area includes Zenodo Account Retrieval for building a durable local inventory of records visible to a selected Zenodo API key. It retrieves published depositions and drafts, stores the results as retrieval-generated `.hdpc` collections backed by shard sessions, and creates completed explorer-only sessions for inspection.

Operational behavior:
- Users can run retrievals with owned keys, accepted shared keys, or accessible institution keys.
- The task uses authenticated deposition listing with `Authorization: Bearer ...`; tokens are never placed in URLs, task history, API responses, logs, or `.hdpc` files.
- Harvesting is rate-limited to 30 requests per minute or less with 100 records per page.
- Large accounts are split into date/datetime windows so retrieval is not constrained by a single 10,000-result search window.
- Dense windows that return page-boundary `400`/`422` responses are split and retried, which allows retrieval to continue when Zenodo rejects page 101-style result windows.
- Pause and cancel are cooperative; resume continues from the saved checkpoint under the same retrieval ID.
- Generated shard sessions have `origin_type="zenodo_deep_retrieval"` and `access_mode="explorer_only"`.
- Completed collections track latest record timestamps and can be used as parents for incremental follow-up retrievals.
- Operators can search collection records, export manifests/CSV/shard archives, compact many small shards into a smaller shard set, and record retention preferences.
- Incremental schedules can be stored per completed collection with daily, weekly, or monthly cadence and a configurable overlap window.
- Deleting the retrieval job from Tools is the explicit cleanup path for generated shard sessions and files.

Recommended operating pattern for large production accounts:
1. Save or accept the target Zenodo credential in Account Configuration.
2. Start with a small maximum record limit to confirm scope and UI behavior.
3. Increase the limit or leave it blank for full retrieval after the sample run succeeds.
4. Monitor retrieved count, shard count, rate-limit waits, and the active window.
5. Open a generated shard from the Tools page to confirm Records Explorer visibility.
6. For later updates, use incremental mode so the next run starts from the previous collection's latest retrieved record timestamp, with a small overlap.
7. Compact only when the shard count is inconvenient for operations; separate shards remain the most transparent retrieval audit trail.

If a host/network interruption stops the worker while the job still displays `PROGRESS`, verify that no retrieval worker is running and then use Resume on the same retrieval. The checkpoint preserves pending windows, generated shards, and dedupe state.

If the frontend and backend are served from different origins, CORS must allow `PATCH`; retention and schedule updates use `PATCH` endpoints and browsers will block them during preflight if the method is missing. To automate stored incremental schedules, wire `execute_due_zenodo_account_retrieval_schedules` into Celery Beat or an equivalent production scheduler.

Production verification on April 30, 2026 completed an account retrieval with `83,657` records into `848` `.hdpc` shards after `11` adaptive splits. The final state was `SUCCESS` with no pending windows. This run confirmed that the strategy works beyond 10,000 records for a real dense production account.

Reference: `zenodo_account_retrieval.md`.

## 8. Public Record Embeds and oEmbed
WebHDP exposes published Zenodo records through public, unauthenticated presentation routes:
- Public landing page: `/p/records/<environment>/<zenodo_record_id>`
- Iframe-safe embed page: `/embed/records/<environment>/<zenodo_record_id>`
- oEmbed endpoint: `/api/v1/oembed?url=<public_record_url>&format=json`

Use `zenodo` for production records and `sandbox` for sandbox records. These routes intentionally use only public Zenodo identifiers; they do not expose WebHDP session IDs or local record IDs.

Configuration:
- `FRONTEND_URL`: default public origin used for generated links.
- `PUBLIC_BASE_URL`: optional override when public pages are served from a different externally reachable origin.
- `OEMBED_FRAME_ANCESTORS`: Content Security Policy allow-list for `/embed/records/...`. Keep this as narrow as practical in production, for example `https://museum.example.org https://exhibit.example.org`.

Operational checks:
- Confirm `GET /api/v1/public/records/zenodo/<record_id>` returns the expected title, DOI, thumbnail, and model preview metadata.
- Confirm `GET /api/v1/oembed?url=<public_record_url>&format=json` returns a raw oEmbed object with `type: "rich"`.
- Test the iframe on the consuming site after changing `OEMBED_FRAME_ANCESTORS`.

## 9. Operational Health Checks
Use these checks before live operation:
- `GET /api/v1/health`
- `POST /api/v1/setup/check`
- `GET /api/v1/admin/pipelines/render/status`
- `GET /api/v1/admin/storage-status`
- Cloud provider tests under `/api/v1/admin/cloud/test/*`
- `GET /api/v1/metadata/workflow-support`
- `GET /api/v2/platform-support`
- `GET /api/v1/tools/zenodo-account-retrieval/context` when validating retrieval tooling

## 10. Routine Operator Runbook
Daily:
- Verify API and supported dependency reachability
- Inspect failed submissions and task failures
- Confirm storage availability and fallback behavior

Before presentations:
- Validate sandbox connectivity
- Run a bounded Zenodo account retrieval if the presentation includes existing-account inventory
- Run a full dry-run submission
- Confirm template preview/validation output
- Preload sample sessions for fallback demonstration

After incidents:
- Collect logs (`logs/app.log`, `logs/error.log`)
- Capture failed submission payload and progress snapshots
- Re-run in sandbox after remediation

## 11. Security and Governance Controls
- JWT authentication for protected endpoints
- Role-based actions for moderator/admin functions
- Session ownership checks on user-scoped data
- Token revocation via logout blocklist
- Zenodo user and institution credentials are encrypted at rest, masked in UI/API responses, and omitted from validation reports and audit details.
- Zenodo key sharing requires recipient acceptance and shares access only to an encrypted credential record.
- Zenodo account retrieval stores only retrieval provenance and returned deposition metadata; it does not store cleartext tokens and generated sessions are explorer-only.

Operational recommendation:
- Restrict admin accounts and enforce strong credentials rotation.
- Set `CREDENTIAL_ENCRYPTION_KEY` explicitly in production and rotate Zenodo keys following institutional policy.

## 12. Data Integrity and Recovery Practices
- Persist `instance/` and session volumes outside ephemeral containers
- Back up DB and session storage
- Keep `.env` under secret management, not in public repos
- Use sandbox for all pre-production validation
- Treat retrieval-generated `.hdpc` shards as persistent inventory artifacts until explicitly deleted through the retrieval job controls

### Operational Backups
WebHDP includes dedicated backup tooling that is separate from user-facing Cloud Storage mirrors. Use it for manual, scheduled, and pre-update backups while keeping SQLite as the default low-user deployment database.

Minimum configuration:
```dotenv
BACKUP_PROVIDER=local
BACKUP_LOCAL_DIR=./backups
BACKUP_REMOTE_PREFIX=/WebHDP/backups
BACKUP_INCLUDE_CREDENTIALS=true
BACKUP_ENCRYPTION_KEY=<strong-backup-secret>
```

Dropbox can be used as the first off-machine backup target when `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, and `DROPBOX_REFRESH_TOKEN` are configured:
```bash
./scripts/backup.py --type pre-update --provider dropbox
```

The backup archive includes an online SQLite backup copy, configured session/input/output paths, optional encrypted credentials, and a manifest with checksums. Cloud backups are refused unless encryption is enabled. To restore, stop backend and worker services first, then run:
```bash
./scripts/restore_backup.py backups/<archive>.tar.gz.enc --force
```

Retention and status checks:
```bash
./scripts/backup_status.py
./scripts/list_backups.py
./scripts/prune_backups.py --provider local          # dry run
./scripts/prune_backups.py --provider local --apply  # delete old local backups
```

Scheduled backups can use a host cron or systemd timer. The command is intentionally plain shell so it works before a VPS or CI/CD system is finalized:
```bash
BACKUP_PROVIDER=dropbox ./scripts/scheduled_backup.sh
```

Example cron entry for a daily 02:30 backup:
```cron
30 2 * * * cd /path/to/webhdp && BACKUP_PROVIDER=dropbox ./scripts/scheduled_backup.sh >> logs/backup.log 2>&1
```

Before applying an update, run:
```bash
BACKUP_PROVIDER=dropbox ./scripts/pre_update.sh
```

To build local production-style images before a registry is available:
```bash
WEBHDP_IMAGE_TAG=local ./scripts/build_images.sh
```

Admin-only backend endpoints are available for operational surfaces and future UI wiring:
- `GET /api/v1/admin/backups/status`
- `GET /api/v1/admin/backups`
- `POST /api/v1/admin/backups`
- `POST /api/v1/admin/backups/prune`

Restore drill checklist: `restore_drill_checklist.md`.

## 13. Release Readiness Checklist
- Setup completed and admin account active
- Storage mode verified and documented
- Renderer/USDZ status consistent with expected pipeline profile
- API smoke tests pass
- End-to-end submission test passes
- Provenance report endpoint returns coherent lineage
- Presentation runbook rehearsed
- `./scripts/release_check.sh` passes locally
- A pre-update backup has been created and at least one restore drill has been completed
