# WebHDP

WebHDP is a web application for preparing, validating, and publishing
heritage-science datasets, with strong support for 3D assets, tabular metadata,
Zenodo workflows, and generated EDM, IIIF, and METS outputs.

Canonical source repository:
`https://github.com/Digital-Humanities-Jena/webhdp`

Current public release: `v0.1.0-alpha.1`

## What WebHDP Does

WebHDP helps cultural-heritage and heritage-science teams turn heterogeneous
source files and metadata spreadsheets into traceable, publication-ready record
sets. It combines upload or local-scan workflows, metadata normalization,
pipeline execution, standards-oriented LOD generation, validation reports,
Zenodo publication support, and persistent local `.hdpc` project state.

Core capabilities:

- Guided session workflow from source files and MSF spreadsheets to records
- Local `.hdpc` project state for record identity, provenance, and reruns
- Metadata extraction, mapping, normalization, and validation
- EDM, IIIF, and METS generation
- Optional local EDM validation via a pinned external validator checkout
- Optional 3D rendering and USDZ conversion services
- Public record pages and oEmbed responses for published records
- Zenodo credential handling with encrypted, masked, user-managed keys
- Zenodo account retrieval into explorer-only `.hdpc` collections
- Docker-based local, server, and operator deployment paths

## Alpha Release Boundary

This is an alpha repository release. The most stable path is the predefined
`render` pipeline and the low-resource `metadata_only` pipeline.

HDP Component installation, Pipeline Constructor workflows, local Docker-backed
component execution, and HPC-Link or SIF-based execution are included for
evaluation and operator validation. Treat them as deployment-specific features
until the target machine or HPC environment has been tested.

This repository does not contain private HPC credentials, local runtime data,
deployment secrets, generated reports, or vendored local-edm-validator source.

## Repository Layout

| Path | Purpose |
|---|---|
| `app.py`, `routes/`, `services/` | Flask API and orchestration layer |
| `frontend/` | Vue 3 user interface |
| `database/`, `migrations/` | Application models, seeds, and migrations |
| `services/hdpc_*` | Local `.hdpc` state and provenance services |
| `services/native_pipeline_*` | Native pipeline and component runtime |
| `external_code/` | Bundled alpha HDP component manifests and selected local services |
| `schema_xsds/`, `docs/metsmods/` | Runtime validation schemas |
| `test_data/workflow_fixtures/` | Curated workflow fixtures for tests and demos |
| `docs/` | User, operator, developer, architecture, and workflow documentation |

## Requirements

For the simplest local Docker setup:

- Git
- Docker Engine or Docker Desktop with Docker Compose v2
- At least 8 GB free disk space
- A shell with `openssl` or another secure random generator

For local development outside Docker:

- Python managed with `uv`
- Node.js 22, matching [.nvmrc](.nvmrc)
- npm

## Get Started: Local Docker

This is the shortest supported path for a fresh clone on a local machine.

```bash
git clone https://github.com/Digital-Humanities-Jena/webhdp.git
cd webhdp
cp .env.example .env
mkdir -p instance hdp-shared/sessions local_input local_output credentials
```

Generate three local secrets:

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Edit `.env` and set at least these values:

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

ZENODO_SANDBOX_API_KEY=
ZENODO_API_KEY=
DROPBOX_APP_KEY=
DROPBOX_APP_SECRET=
DROPBOX_REFRESH_TOKEN=
GOOGLE_APPLICATION_CREDENTIALS=
HPC_LINK_BASE_URL=
HPC_LINK_API_KEY=
```

Start WebHDP:

```bash
docker compose up -d --build
```

Open the first-run setup wizard:

```text
http://localhost:8080/setup?setup_token=<generated_setup_token>
```

Verify the stack:

```bash
docker compose ps
curl http://localhost:8080/api/v1/health
```

Expected result:

- `backend`, `frontend`, `worker`, and `redis` are running.
- The health endpoint returns JSON successfully.
- The UI opens at `http://localhost:8080`.

For the expanded local installation guide, see
[docs/guides/docker_quickstart.md](docs/guides/docker_quickstart.md).

## Optional Local Processing Services

The default local Docker setup keeps compute-heavy processing conservative. On a
capable workstation, local renderer/USDZ services and Docker-backed HDP
Components can be enabled deliberately:

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

Restart after changing `.env`:

```bash
docker compose up -d --build
```

Keep `ANY_TO_USDZ_PLATFORM=linux/amd64` on Apple Silicon unless the Admin USDZ
conversion test passes with another platform. The default uses the official
Blender runtime with USD export support.

## Optional Local EDM Validator

WebHDP integrates with
[Digital-Humanities-Jena/local-edm-validator](https://github.com/Digital-Humanities-Jena/local-edm-validator)
as a pinned external checkout. The validator source is not vendored in this
repository.

To use the managed validator overlay:

```bash
make local-edm-validator-setup
docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml up -d --build
```

Then set or keep these values in `.env`:

```dotenv
ENABLE_LOCAL_EDM_VALIDATION=true
LOCAL_EDM_VALIDATOR_REQUIRED=true
LOCAL_EDM_VALIDATOR_URL=http://local-edm-validator:8080
```

The EDM Config page reports validator health, version, source ref, build time,
and image tag from `/actuator/info`.

Full runbook:
[docs/guides/local_edm_validator.md](docs/guides/local_edm_validator.md).

## Deployment Guides

- Local Docker quickstart:
  [docs/guides/docker_quickstart.md](docs/guides/docker_quickstart.md)
- Docker deployment and compose profiles:
  [docs/docker_deployment_guide.md](docs/docker_deployment_guide.md)
- HPC local-mode setup:
  [docs/guides/hpc_local_mode_setup.md](docs/guides/hpc_local_mode_setup.md)
- Single-GPU HPC setup:
  [docs/guides/hpc_single_gpu_setup_guide.md](docs/guides/hpc_single_gpu_setup_guide.md)
- Security and credential handling:
  [docs/guides/security_and_credentials.md](docs/guides/security_and_credentials.md)

## First Workflow To Try

For manual UI testing, start with:

- `test_data/workflow_fixtures/msf/workflow_minimal.csv`
- `test_data/workflow_fixtures/cases/root_stem_mixed/`

Use `metadata_only` first if renderer or USDZ conversion is not enabled.

For a command-line development check, use the fixture-backed workflow to verify
that the codebase can scan local files, analyze an MSF, persist `.hdpc` state,
and expose records:

```bash
make golden-workflow
```

## Documentation

Start here:

- Documentation hub: [docs/README.md](docs/README.md)
- End-user workflow guide:
  [docs/guides/end_to_end_user_guide.md](docs/guides/end_to_end_user_guide.md)
- Operations and setup:
  [docs/guides/operations_and_setup_guide.md](docs/guides/operations_and_setup_guide.md)
- Troubleshooting:
  [docs/guides/troubleshooting.md](docs/guides/troubleshooting.md)
- Architecture overview:
  [docs/architecture/system_architecture.md](docs/architecture/system_architecture.md)
- `.hdpc` schema:
  [docs/architecture/hdpc_schema.md](docs/architecture/hdpc_schema.md)
- API reference:
  [docs/api/webhdp_api_reference.md](docs/api/webhdp_api_reference.md)
- API examples:
  [docs/api/webhdp_api_examples.md](docs/api/webhdp_api_examples.md)
- Release walkthrough videos:
  [docs/guides/video_guides/release_walkthroughs.md](docs/guides/video_guides/release_walkthroughs.md)
- Planned future updates:
  [docs/guides/planned_future_updates.md](docs/guides/planned_future_updates.md)

Developer entry points:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/development/onboarding.md](docs/development/onboarding.md)
- [docs/development/first_pr_walkthrough.md](docs/development/first_pr_walkthrough.md)
- [docs/development/architecture_map.md](docs/development/architecture_map.md)
- [docs/development/first_hdp_component.md](docs/development/first_hdp_component.md)

## Development

Install dependencies:

```bash
make setup
```

Common commands:

| Command | Purpose |
|---|---|
| `make help` | List available commands |
| `make doctor` | Run a contributor environment health report |
| `make test` | Run backend tests, component validation, and frontend unit tests |
| `make docs-check` | Validate developer docs and docs catalog entries |
| `make api-contract-check` | Fail if `docs/api/openapi.json` is stale |
| `make hdp-components-check` | Validate bundled HDP Component manifests |
| `make release-assets-check` | Validate curated release media/assets |
| `make golden-workflow` | Run the local fixture-backed onboarding workflow |
| `./scripts/release_check.sh` | Run the full release gate |

The full release gate includes backend tests, frontend tests/build/audit,
HPC-Link backend tests, HPC-Link frontend lint/build/audit, Compose validation,
release asset checks, and script syntax checks.

## Security

Never commit `.env`, credentials, local databases, logs, session directories,
generated reports, local validator checkouts, or deployment-specific HPC
configuration.

WebHDP stores user and institution Zenodo API keys encrypted at rest and returns
only masked previews. See [SECURITY.md](SECURITY.md) and
[docs/guides/security_and_credentials.md](docs/guides/security_and_credentials.md).

## Credits, Funding, And Citation

WebHDP was initiated and is lead-developed by Dominik Ukolov, Professorship for
Digital Humanities (Image/Object), Friedrich Schiller University Jena, and
Research Group DIGITAL ORGANOLOGY, Leipzig University.

The software was developed as part of 3DBigDataSpace, officially described as
"3D Big Data for the Data Space for Cultural Heritage", funded by the European
Union under Grant Agreement No. 101173385. Development will continue as part of
INFINITY, officially titled "Multidimensional knowledge-based annotation for
ethical context-aware heritage data life cycles", funded by the European
Commission under Grant Agreement No. 101233051.

Citation metadata is provided in [CITATION.cff](CITATION.cff). Author and
acknowledgement details are maintained in [AUTHORS.md](AUTHORS.md).

## Release And Publishing

- Publishing checklist: [PUBLISHING.md](PUBLISHING.md)
- Release notes: [RELEASE_NOTES.md](RELEASE_NOTES.md)
- Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Security policy: [SECURITY.md](SECURITY.md)

## License

WebHDP is licensed under the European Union Public Licence v. 1.2 or later
(`EUPL-1.2`). See [LICENSE](LICENSE).

Third-party dependencies, standards schemas, external tools, and referenced
standards documentation retain their own licenses and terms. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
