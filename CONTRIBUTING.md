# Contributing To WebHDP

Thank you for helping improve WebHDP. This project supports real heritage-science publication workflows, so contributions should preserve traceability, security, and reproducibility as much as visible product behavior.

Start here:

1. New to the project: `docs/development/onboarding.md`
2. Ready to place a change: `docs/development/contributor_handbook.md`
3. Need a concrete pattern: `docs/development/examples.md`
4. Changing runtime behavior: `docs/architecture/system_architecture.md`

## Project Shape

WebHDP is a multi-part application:

- Flask API at the repository root: `app.py`, `routes/`, `services/`, `database/`, `schemas/`, `tasks.py`
- Vue 3 frontend: `frontend/`
- Optional FastAPI/React HPC bridge: `hpc-link/`
- Optional processing services: `external_code/fast_renderer`, `external_code/any_to_usdz`, and a local EDM validator integration
- Operator, API, architecture, and user docs: `docs/`

The canonical product contract is documented in `README.md` and `docs/architecture/system_architecture.md`.

## Development Setup

1. Install Git, Docker, Python 3.11, and Node.js 22.12 or newer.
2. Copy `.env.example` to `.env` and fill only local development values.
3. Install backend dependencies:
   - `uv sync --group dev`
4. Install frontend dependencies:
   - `cd frontend && npm ci`
5. If you work on HPC Link:
   - `make hpc-link-test`
   - `cd hpc-link/frontend && npm ci`

Docker startup is documented in `README.md` and `docs/docker_deployment_guide.md`.

## Fast Onboarding Paths

- Documentation-only: read `docs/development/onboarding.md`, edit the relevant doc, then run `git diff --check`.
- Backend/API: install root Python dependencies, change `routes/` plus `services/`, and run focused `uv run pytest ...` tests before the broader suite.
- Frontend: work under `frontend/src/`, keep API calls in `frontend/src/services/`, and run `npm run test:unit` plus `npm run build`.
- Full-stack workflow: use `docker compose up --build` and verify the behavior through `http://localhost:8080`.
- HPC Link: stay under `hpc-link/` and run its backend/frontend checks.

The examples cookbook in `docs/development/examples.md` shows common implementations end to end, including tests and documentation updates.

## Where Changes Belong

- Add or change HTTP behavior in `routes/`; keep business rules in `services/`.
- Add reusable request/response validation models in `schemas/`.
- Add relational app state in `database/models.py` plus an Alembic migration under `migrations/versions/`.
- Add long-running or scheduled work in `tasks.py` and keep status/progress payloads stable.
- Add Vue API calls in `frontend/src/services/`, cross-view state in `frontend/src/stores/`, and page-level workflows in `frontend/src/views/`.
- Add component-level UI in `frontend/src/components/`.
- Keep HPC Link changes inside `hpc-link/` unless the WebHDP integration route or client also changes.
- Update `docs/` whenever behavior, setup, API contracts, operator duties, or contributor expectations change.

## Checks Before Opening A Pull Request

Run the checks that match the area you changed:

- Backend tests: `uv run pytest`
- Frontend unit tests: `cd frontend && npm run test:unit`
- Frontend build: `cd frontend && npm run build`
- Frontend end-to-end tests when workflow routing or browser flows change: `cd frontend && npm run test:e2e`
- HPC Link backend tests: `cd hpc-link && python -m pytest`
- HPC Link frontend checks: `cd hpc-link/frontend && npm run lint && npm run build`
- Docker validation: `make compose-check`
- Production compose validation is included in `make compose-check`

If a relevant check cannot run locally, call that out in the pull request.

## Pull Request Expectations

Each pull request should explain:

- The user or operator problem being solved
- The changed API, database, task, UI, or documentation surfaces
- The tests or manual checks performed
- Any migrations, feature flags, environment variables, or deployment steps
- Any remaining risks or intentional follow-up work

Prefer small, coherent pull requests. A feature may touch multiple layers, but the reason for each layer change should be obvious from the description and tests.

## Repository Hygiene

- Do not commit `.env`, credentials, local databases, logs, session directories, build outputs, dependency directories, or generated caches.
- Keep large dataset/model/video assets outside normal Git history unless the project owner explicitly approves Git LFS use.
- Use `.env.example` for configuration names and placeholders only.
- Preserve user data and session provenance. Do not delete or rewrite persisted records as a convenience for implementation.
- Do not expose cleartext tokens in responses, logs, validation reports, audit events, tests, fixtures, or documentation.

## Security

If you find a vulnerability, follow `SECURITY.md` instead of opening a public issue.
