# Docker Deployment & Architecture Guide

This document explains the multi-architecture Docker setup and the tiered Docker Compose strategy used in the HDP Web Interface.

## 0. Deployment Prerequisites

Before running any deployment commands, ensure the following files are available on the server and configured correctly. For an existing installation, follow the [alpha.3 upgrade checklist](guides/upgrade_alpha3.md) for backup, migration and staging.

### Files to Transfer
Transfer the **entire project directory** to your server. The Docker build process requires the full source code context.
*   **Core Logic:** `backend/`, `frontend/`, `services/`, `routes/`, `database/`
*   **Config & Startup:** `app.py`, `config.py`, `celery_app.py`, `requirements.txt`
*   **Docker Config:** `docker-compose.yml` and any specific override files (e.g., `docker-compose.low-resource.yml`)
*   **External Modules:** `external_code/` (Required for build context even if services are disabled)

The deployment uses only the WebHDP services defined in this repository and does not require any external compatibility container.

### Environment Configuration (`.env`)
Create a real `.env` file in the project root before running Docker Compose. `.env.example` is documentation only and is not loaded by the production compose stack.

**Critical Adaptations for Production:**
1.  **`FLASK_ENV`**: Set to `production`.
2.  **`SECRET_KEY`**: Production HS256 JWT signing requires at least 32 bytes. Generate a fresh random value (for example, `openssl rand -hex 32`) for a new deployment; keep the existing strong value across upgrades unless rotating it intentionally.
3.  **`CREDENTIAL_ENCRYPTION_KEY`**: Generate a separate strong secret for encrypted Zenodo/HPC credentials.
4.  **`SETUP_BOOTSTRAP_TOKEN`** or **`DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`**: Provide one first-run admin bootstrap path.
5.  **`FRONTEND_URL`**: Set to your public domain (e.g., `https://hdp.yourdomain.com`).
6.  **`PUBLIC_BASE_URL`**: Optional override for public record and oEmbed URLs when they are served from a different external origin.
7.  **`OEMBED_FRAME_ANCESTORS`**: CSP allow-list for `/embed/records/...` iframe consumers. Use `'self'` or explicit trusted origins; do not use `*` in production.
8.  **`WEBHDP_SESSIONS_PATH`**: Set to a valid absolute path on the **host** server where session data will be stored (e.g., `/mnt/data/sessions`). Ensure this directory exists.
9.  **`GOOGLE_APPLICATION_CREDENTIALS`**: Point to the absolute path of your Google Cloud JSON key on the **host** machine.
10. **Mail Settings**: Configure `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, etc., for email notifications. Local development may use `MFA_DEVELOPMENT_CODE_DELIVERY=inline` with `FLASK_ENV=development`; production ignores this helper and must have real mail delivery or another configured login policy.

**Example `.env` snippet:**
```dotenv
FLASK_ENV=production
SECRET_KEY=<generated_secret_key>
CREDENTIAL_ENCRYPTION_KEY=<generated_credential_secret>
SETUP_BOOTSTRAP_TOKEN=<generated_setup_token>
FRONTEND_URL=https://hdp.example.org
PUBLIC_BASE_URL=https://hdp.example.org
OEMBED_FRAME_ANCESTORS=https://museum.example.org
WEBHDP_SESSIONS_PATH=/var/www/hdp/sessions
GOOGLE_APPLICATION_CREDENTIALS=/etc/hdp/google-credentials.json
MAIL_SERVER=smtp.example.org
MAIL_USERNAME=<smtp_user>
MAIL_PASSWORD=<smtp_password>
MAIL_TIMEOUT=5
```

When using `SETUP_BOOTSTRAP_TOKEN`, start first-run setup from
`https://hdp.example.org/setup?setup_token=<generated_setup_token>`. If the
frontend and backend are served from different origins, `CORS_ORIGINS` must
include the frontend origin so browser preflight requests can send the setup
authorization header.

---

## 1. Rendering Service Architecture

### How it works:
- **Fast Renderer:** supports native **ARM64** (Apple Silicon M1/M2/M3) and **AMD64** builds.
- **Any-to-USDZ:** defaults to `linux/amd64` through `ANY_TO_USDZ_PLATFORM=linux/amd64`, even on Apple Silicon. This deliberately uses the official Blender runtime with working USD export support. Docker Desktop runs it through emulation on ARM Macs.
- **Deep readiness:** the converter health check verifies that Blender can actually export a USD stage, not only that the HTTP service is listening.

Native ARM64 Blender packages from Linux distributions can start successfully
while missing the USD export operator required for USDZ conversion. Override
`ANY_TO_USDZ_PLATFORM` only after the Admin USDZ conversion test passes on the
target platform.

---

## 2. Docker Compose Strategies
We use the **Override Pattern** to manage different resource requirements and environment settings without duplicating service definitions.

### Scenario A: Limited Web Server (Standard Production)
**File:** `docker-compose.yml` (Base)
- **Goal:** Stability and safety on constrained hardware.
- **Constraints:** Strict CPU limits (0.5 - 1.0 CPU) and low memory reservations.
- **Runtime policy:** Server/VPS mode is conservative. Compute-heavy HDP Components such as renderer and USDZ conversion require HPC-Link unless those steps are disabled.
- **Usage:**
  ```bash
  docker compose up -d --build
  ```

### Scenario B: Local Workstation Full-Function Docker
**Files:** `docker-compose.yml` plus optional `docker-compose.dev.yml`
- **Goal:** Run the full WebHDP workflow on a capable local machine without HPC.
- **Target machines:** Mac, Windows/Linux workstation, lab PC, or developer machine with enough CPU/RAM/disk for Blender-based containers.
- **Runtime policy:** This is the only Docker class where local renderer/USDZ execution should be enabled without HPC-Link.
- **Environment:**
  ```dotenv
  WEBHDP_DEPLOYMENT_MODE=local
  WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true
  COMPOSE_PROFILES=local-hdp-components
  WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST=ghcr.io/hdp-components/*,webhdp-*
  WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES=false
  ANY_TO_USDZ_PLATFORM=linux/amd64
  STORAGE_MODE=server_only
  ```
- **Usage:**
  ```bash
  docker compose up -d --build
  ```

For mounted-folder batch scans on the workstation, set `STORAGE_MODE=local` and mount `LOCAL_INPUT_HOST_PATH`/`LOCAL_OUTPUT_HOST_PATH` to host folders intentionally selected for WebHDP.

### Scenario C: MacBook M1/M2 Development
**File:** `docker-compose.dev.yml` (Override)
- **Goal:** Maximum local performance and developer productivity.
- **Features:**
    - Unlocks CPU limits (up to 6.0 CPUs for rendering).
    - Increases memory limits to 4GB.
    - Enables local volume mounting for hot-reloading code.
    - Builds native ARM64 images where supported; the Any-to-USDZ converter
      intentionally uses `linux/amd64` unless `ANY_TO_USDZ_PLATFORM` is changed
      and the converter test passes.
- **Usage:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
  ```

### Scenario D: High-Performance Computing (HPC)
**File:** `docker-compose.hpc.yml` (Override)
- **Goal:** Massive batch processing throughput.
- **Features:**
    - Removes most resource constraints (allocates up to 32 CPUs and 64GB RAM per node).
    - Optimizes `OMP_NUM_THREADS` for high-core count processors.
    - Enables NVIDIA GPU passthrough configuration (if supported by the host).
- **Usage:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.hpc.yml up -d --build
  ```

---

### Scenario E: Linux HPC (Limitless)
**File:** `docker-compose.linux-hpc.yml` (Override)
- **Goal:** Utmost throughput on dedicated, high-end compute nodes.
- **Features:**
    - Removes all CPU and RAM limits.
    - Enables `local_storage` mode by default.
    - Optimized for high core count machines.
- **Usage:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.linux-hpc.yml up -d --build
  ```

---

### Scenario F: Low-Resource Linux Server
**File:** `docker-compose.low-resource.yml` (Override)
**Goal:** Minimal resource footprint for servers where rendering is not required.
**Features:**
    - **Disables** `fast-renderer` and `any-to-usdz` services completely.
    - Application logic strictly bypasses these steps.
    - Generates placeholder metadata/thumbnails to ensure valid EDM/Zenodo records.
    - Keeps the deployment in server/VPS mode; do not enable workstation-local compute on this class.
**Usage:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.low-resource.yml up -d --build
  ```

---

### Optional: Managed Local EDM Validator
**File:** `docker-compose.edm-validator.yml` (Override)
**Goal:** Run [Digital-Humanities-Jena/local-edm-validator](https://github.com/Digital-Humanities-Jena/local-edm-validator) as part of the WebHDP Compose project instead of pointing WebHDP at a separately started validator.
**Detailed runbook:** `guides/local_edm_validator.md`
**Features:**
    - Builds the validator REST service from `LOCAL_EDM_VALIDATOR_REPO`.
    - Starts the required PostgreSQL, MongoDB, Solr, and MinIO services.
    - Overrides backend and worker traffic to `http://local-edm-validator:8080`.
    - Exposes the validator on `${LOCAL_EDM_VALIDATOR_PORT:-18080}` for local smoke tests.
    - Publishes source revision and image tag metadata through `/actuator/info` for WebHDP status reporting.

**Setup:**
  ```bash
  git clone https://github.com/Digital-Humanities-Jena/local-edm-validator external_code/local-edm-validator
  export LOCAL_EDM_VALIDATOR_SOURCE_REF="$(git -C external_code/local-edm-validator rev-parse --short HEAD)"
  docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml up -d --build
  ```

After startup, confirm the managed validator is reachable and identifiable:

  ```bash
  curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/health
  curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/info
  ```

If the validator is managed outside WebHDP, keep using `LOCAL_EDM_VALIDATOR_URL`, for example `http://host.docker.internal:18080` from Docker or `http://localhost:18080` from a host process.

---

## 3. Permissions & Security (Critical)

The backend runs as the non-root user `hdpuser`. Check the UID and GID of the
actual release image with `docker run --rm --entrypoint id IMAGE` and account for
any host UID mapping. Use that identity to provision dedicated bind mounts for
`instance/` (database and Link data), `WEBHDP_SESSIONS_PATH` (uploads and
results), and any mapped log directory. On a host without UID remapping, an
operator can create a new private directory with
`install -d -m 0700 -o UID -g GID DIRECTORY`. If approved processes use different
identities, give only their shared group or ACL the required access. Check
access as the actual backend and worker users before startup.

For data that already exists, stop writers and review ownership and mode for
the mounted tree, including SQLite journals, lock files and backups. Do not
recursively open write access to other users. Restrict `.env` and host secret
files to the required operator or service identity and keep them outside the
frontend root and build context.

---

## 4. SQLite Production Operation

SQLite is the default database for the first low-user deployment. The application enables foreign keys, a 30 second busy timeout, and WAL mode for file-backed SQLite databases. This is appropriate for one backend container and one worker container with modest write concurrency.

Use the operational backup tooling before every update. It creates an online SQLite backup copy, archives the configured persistent paths, writes manifest/checksum metadata, and can upload an encrypted archive to Dropbox:

```bash
read -r -s -p 'Backup encryption secret: ' BACKUP_ENCRYPTION_KEY
export BACKUP_ENCRYPTION_KEY
./scripts/backup.py --type pre-update --provider dropbox
unset BACKUP_ENCRYPTION_KEY
```

Local-only backups are also supported:

```bash
read -r -s -p 'Backup encryption secret: ' BACKUP_ENCRYPTION_KEY
export BACKUP_ENCRYPTION_KEY
./scripts/backup.py --type manual --provider local
unset BACKUP_ENCRYPTION_KEY
./scripts/list_backups.py
```

Restore is intentionally explicit and destructive only with `--force`:

```bash
./scripts/restore_backup.py backups/<archive>.tar.gz.enc --force
```

Apply retention and inspect health:

```bash
./scripts/backup_status.py
./scripts/prune_backups.py --provider local --apply
```

For scheduled operation, run the shell helper from cron or systemd:

```bash
BACKUP_PROVIDER=dropbox ./scripts/scheduled_backup.sh
```

For updates, use the pre-update helper before rebuilding/restarting services:

```bash
BACKUP_PROVIDER=dropbox ./scripts/pre_update.sh
```

The helper runs release checks before touching live data, enables maintenance
mode, waits for Celery work to drain, creates an encrypted pre-update backup,
performs an isolated restore drill, applies migrations, and then runs a
readiness check. Production image variables should use immutable version or Git
SHA tags rather than `latest`; `scripts/check_release_images.py` enforces this
when `CHECK_RELEASE_IMAGES=true`.

Session artifact cleanup is intentionally separate from login/session expiry.
Leave `SESSION_ARTIFACT_CLEANUP_ENABLED=false` until backup, restore, and
retention procedures are operational. When enabled, cleanup uses
`SESSION_ARTIFACT_RETENTION_SECONDS`.

Manual fallback: back up SQLite by using the online backup tooling above, or stop the stack and copy `instance/hdp_web.db` together with any `-wal` and `-shm` sidecar files:

```bash
docker compose stop backend worker
cp instance/hdp_web.db instance/hdp_web.db.backup.$(date +%Y%m%d%H%M%S)
cp instance/hdp_web.db-wal instance/hdp_web.db-wal.backup.$(date +%Y%m%d%H%M%S) 2>/dev/null || true
cp instance/hdp_web.db-shm instance/hdp_web.db-shm.backup.$(date +%Y%m%d%H%M%S) 2>/dev/null || true
docker compose start backend worker
```

SQLite should remain the default for low-user deployments. Revisit the database choice only if you see repeated `database is locked` errors, need multiple backend or worker replicas, have high concurrent writes, need high availability, or store the database on unreliable network storage.

---

## 5. Summary of Performance Impact

| Environment | Architecture | Rendering Mode | Expected Performance |
| :--- | :--- | :--- | :--- |
| **Mac M1 (Old)** | amd64 (Emulated) | Software (Emulated) | **Very Slow** (~160s/model) |
| **Mac M1 (New)** | arm64 (Native) | Software (Native) | **Fast** (<30s/model) |
| **Web Server** | amd64 (Native) | Software (Native) | **Moderate** (Limited by CPU) |
| **HPC Node (Limitless)** | amd64 (Native) | Software/GPU | **Maximum** (Unconstrained) |

## 6. Maintenance Notes
When adding new system dependencies, ensure they are compatible with both the Debian-based ARM64 package manager and the AMD64 tarball environment.
