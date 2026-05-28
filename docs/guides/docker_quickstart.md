# Docker Quickstart

This guide is the shortest supported path from a fresh clone to a local WebHDP
instance. It is intended for new users who want to evaluate the alpha release on
their own machine before reading the full operations guide.

## Prerequisites

- Git
- Docker Engine or Docker Desktop with Docker Compose v2
- At least 8 GB free disk space for images, session data, and test artifacts
- A shell that can run `openssl`; use another secure random generator if
  `openssl` is not available

## 1. Clone The Repository

```bash
git clone https://github.com/Digital-Humanities-Jena/webhdp.git
cd webhdp
```

## 2. Create Local Configuration

```bash
cp .env.example .env
mkdir -p instance hdp-shared/sessions local_input local_output credentials
```

## Best-Practice Local Docker Setup

Recommended default:

- Use Docker Compose on the local machine instead of installing backend,
  frontend, Redis, and worker dependencies directly on the host.
- Start with `STORAGE_MODE=server_only`. This keeps browser uploads and session
  data inside repository-local Docker mounts and avoids accidental access to
  broad host folders.
- Keep local renderer/USDZ services disabled for the first health check. Enable
  them only after the basic workflow is healthy and the machine has enough CPU,
  RAM, and disk.
- Leave Zenodo, Dropbox, Google, SMTP, and HPC-Link credentials empty for the
  first setup. Add credentials later through the UI or through local
  deployment-only `.env` values.
- Never commit `.env`, `credentials/`, `instance/`, `hdp-shared/`,
  `local_input/`, or `local_output/`.
- Use a unique `SETUP_BOOTSTRAP_TOKEN` for every local clone. Delete or rotate
  it after setup if the machine is shared.
- Treat `docker-compose.dev.yml` as a developer override, not as the default
  first-time user path.

Edit `.env` and set local development values:

```dotenv
FLASK_ENV=development
SECRET_KEY=<generated_secret>
CREDENTIAL_ENCRYPTION_KEY=<generated_credential_secret>
SETUP_BOOTSTRAP_TOKEN=<generated_setup_token>
FRONTEND_URL=http://localhost:8080
PUBLIC_BASE_URL=http://localhost:8080
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
WEBHDP_HTTP_PORT=8080
STORAGE_MODE=server_only
ENABLE_LOCAL_EDM_VALIDATION=false
LOCAL_EDM_VALIDATOR_REQUIRED=false
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true
```

Generate the three secret values with:

```bash
openssl rand -hex 32
```

Zenodo keys, Dropbox credentials, Google credentials, SMTP credentials, and
HPC-Link settings are optional for this quickstart. Leave them empty unless you
are deliberately testing those integrations.

For a clean local setup, explicitly keep these optional values empty:

```dotenv
ZENODO_SANDBOX_API_KEY=
ZENODO_API_KEY=
DROPBOX_APP_KEY=
DROPBOX_APP_SECRET=
DROPBOX_REFRESH_TOKEN=
GOOGLE_APPLICATION_CREDENTIALS=
HPC_LINK_BASE_URL=
HPC_LINK_API_KEY=
```

Use `chmod` or `chown` only if Docker cannot write to the mounted directories.
On Linux, the container user is usually UID `1000`:

```bash
chown -R 1000:1000 instance hdp-shared local_input local_output
```

Avoid broad permissions such as `chmod -R 777` unless this is a disposable local
test clone.

## 3. Start WebHDP

```bash
docker compose up -d --build
```

Open the setup wizard:

```text
http://localhost:8080/setup?setup_token=<generated_setup_token>
```

Create the first administrator account, complete setup, and then log in.

## 4. Verify The Instance

Run:

```bash
docker compose ps
curl http://localhost:8080/api/v1/health
```

Expected result:

- `backend`, `frontend`, `worker`, and `redis` are running.
- The health endpoint returns a successful JSON response.
- The UI opens at `http://localhost:8080`.

## 5. Optional Local Processing Services

The default quickstart keeps compute-heavy services disabled unless the user
opts into them. On a capable workstation, local renderer/USDZ services can be
enabled by setting:

```dotenv
WEBHDP_DEPLOYMENT_MODE=local
WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true
COMPOSE_PROFILES=local-hdp-components
WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST=ghcr.io/hdp-components/*,webhdp-*
WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES=false
ANY_TO_USDZ_PLATFORM=linux/amd64
ENABLE_RENDERER=true
ENABLE_USDZ_CONVERSION=true
```

Then restart:

```bash
docker compose up -d --build
```

Use the full [Docker Deployment Guide](../docker_deployment_guide.md) before
using these settings on shared or public infrastructure.

Best practice for local processing:

- Enable local processing only on a workstation or lab machine where Blender
  and conversion workloads are acceptable.
- Keep `ANY_TO_USDZ_PLATFORM=linux/amd64` unless the Admin USDZ conversion test
  passes on another platform.
- Use `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST` to limit which local component
  images can run.
- Use `STORAGE_MODE=local` only when the user deliberately wants mounted-folder
  scans from `LOCAL_INPUT_HOST_PATH` and `LOCAL_OUTPUT_HOST_PATH`.
- Use `metadata_only` as the first test pipeline if renderer or USDZ health is
  not yet proven.

## 6. Optional Local EDM Validator

For EDM validation, WebHDP can either use an already running validator via
`LOCAL_EDM_VALIDATOR_URL` or start a managed validator stack:

```bash
git clone https://github.com/Digital-Humanities-Jena/local-edm-validator external_code/local-edm-validator
export LOCAL_EDM_VALIDATOR_SOURCE_REF="$(git -C external_code/local-edm-validator rev-parse --short HEAD)"
docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml up -d --build
```

Set these values when the managed validator is used:

```dotenv
ENABLE_LOCAL_EDM_VALIDATION=true
LOCAL_EDM_VALIDATOR_REQUIRED=true
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true
```

The detailed runbook is [Local EDM Validator](local_edm_validator.md).

## 7. First Test Workflow

Use the included sample data:

- MSF: `test_data/workflow_fixtures/msf/workflow_minimal.csv`
- Source ZIP fixture: create one from a fixture case such as
  `test_data/workflow_fixtures/cases/root_stem_mixed/`

In the UI, start a new upload workflow, choose the MSF-driven path, upload the
sample files, complete MSF preflight, and continue to file review. This verifies
that cloning, Docker startup, authentication, upload handling, session storage,
and worker processing are connected.

## 8. Routine Local Operations

Use these commands for ordinary local operation:

```bash
docker compose ps
docker compose logs --tail=200 backend worker frontend
docker compose restart backend worker frontend
docker compose down
```

For updates:

```bash
git pull
docker compose build
docker compose up -d
```

Before deleting a local clone, export or back up any sessions that matter from
`hdp-shared/sessions` and the SQLite database under `instance/`.

Local deployment is healthy enough for evaluation when:

- the setup wizard completes
- login works
- `curl http://localhost:8080/api/v1/health` succeeds
- a small upload reaches scanned state
- the first test workflow can open records or continue to metadata review
- optional services that are enabled also pass their Admin health checks
