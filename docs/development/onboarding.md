# WebHDP Developer Onboarding

Use this guide when you are new to the project and want the shortest reliable path from clone to first contribution.

## 1. First 10 Minutes

Read these in order:

1. `README.md` for the product goal, quick start, and current workflow contract.
2. `CONTRIBUTING.md` for contribution expectations and the core checks.
3. `docs/development/first_pr_walkthrough.md` for a step-by-step first contribution path.
4. `docs/development/troubleshooting_decision_tree.md` when setup or local checks fail.
5. `docs/development/architecture_map.md` for ownership boundaries across frontend, backend, tasks, and persistence.
6. `docs/development/developer_glossary.md` for WebHDP-specific implementation vocabulary.
7. `docs/development/pr_scope_examples.md` when deciding whether a PR is reviewable or should be split.
8. `docs/development/known_warnings.md` when a passing command still prints noisy warnings.
9. `docs/development/contributor_handbook.md` for the codebase map and where changes belong.
10. `docs/development/examples.md` for copyable patterns before you implement.
11. `docs/development/first_hdp_component.md` when you want to turn a container into an installable HDP Component.
12. `docs/development/good_first_changes.md` if you want a scoped starter task.
13. `docs/architecture/system_architecture.md` when your change touches workflow state, `.hdpc`, publishing, tasks, or storage modes.

You do not need to understand the whole system before starting. Start with the surface you are changing and follow the local conventions around it.

If you use VS Code or Codespaces, the fastest setup path is the devcontainer in `.devcontainer/`. See `docs/development/devcontainer.md`.

## 2. Choose Your Development Track

Most repeated commands are wrapped in the repository `Makefile`:

```bash
make help
make setup
make doctor
make golden-workflow
make verify-onboarding
```

If you add, remove, or rename an API route, run:

```bash
make api-contract
make api-contract-check
```

### Documentation-Only

Best for first contributions, glossary updates, API examples, setup notes, and clarifying operator guidance.

```bash
make docs-check
git diff --check
```

Check that every referenced file path exists and that setup commands still match `README.md`, `CONTRIBUTING.md`, `frontend/package.json`, and `.github/workflows/ci.yml`.

### HDP Component Development

Best when you are wrapping a container, command-line tool, validator, or model so WebHDP can run it through Playground or a native pipeline.

```bash
uv run python scripts/validate_hdp_components.py external_code/<component_name>
make hdp-components-check
```

Start with `first_hdp_component.md`, then use `../guides/hdp_component_hpc_installation.md` when choosing local Docker or HPC/Singularity installation strategy.

### Backend API Or Service

Best for Flask routes, service logic, database-backed behavior, tasks, credentials, publishing, and `.hdpc` integration.

```bash
uv sync --group dev
cp .env.example .env
uv run pytest
```

For a focused loop:

```bash
uv run pytest tests/test_name.py
```

Use `WEBHDP_INLINE_TASKS=true` when you need local single-process task behavior without a Celery worker.

### Frontend

Best for Vue views, route guards, workflow state, API clients, public pages, and dashboard/admin screens.

```bash
cd frontend
npm ci
npm run test:unit
npm run build
```

Use Playwright when browser routing, auth flow, storage, modals, or multi-step workflow behavior changes:

```bash
npx playwright install chromium firefox
npm run test:e2e:core
npm run test:e2e:backend
```

Both suites are required in CI and `scripts/release_check.sh`. The backend suite starts an isolated Flask API with temporary databases and exercises the production permission, reservation, dispatch, cancellation, and worker-finalization paths. Broker delivery and component computation use fixtures. It requires the repository's `.venv`, created by `uv sync --frozen --group dev`. Use `npm run test:e2e` for the remaining browser scenarios.

The GitHub Actions browser job uses Ubuntu 24.04 for compatibility with the
locked Playwright release.

Remote HPC validation is separate: when Draco is available, verify allocation readiness, remote session path mapping, job timeout and disconnection behavior, artifact retrieval, and the handling of worker interruption while a scheduler job remains active. Local contract and recovery tests do not contact Draco.

### Full Local Stack

Best when you need to exercise the app end to end with backend, frontend, Redis, workers, and optional processing services.

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8080` and complete `/setup` on first run. Use `docs/docker_deployment_guide.md` for deployment profiles.

### Golden Sample Workflow

Best when you want a quick local proof that scanning, `.hdpc` creation, inspection, and MSF matching work before starting feature work.

```bash
make golden-workflow
```

Details: `docs/development/golden_workflow.md`.

### HPC Link

Best for the optional bridge that connects WebHDP to HPC resources.

```bash
cd hpc-link
uv run --with pytest --with pytest-asyncio --with-requirements requirements.lock python -m pytest
```

The gateway image installs the hash-pinned dependencies in
`hpc-link/requirements.lock`. After changing `hpc-link/requirements.txt`, run the
compile command recorded at the top of the lockfile from the gateway directory,
then audit and test the resulting lock.

For the HPC Link frontend:

```bash
cd hpc-link/frontend
npm ci
npm run lint
npm run build
```

### In-App Developer Mode

After logging in as an admin, moderator, or user with `developer_access`, open:

```text
/developer
```

The page shows non-secret runtime diagnostics, key onboarding commands, feature flags, API contract status, and developer documentation links.

## 3. Make A First Change

Good first changes usually have one clear owner:

- Documentation clarification in `docs/`
- Frontend copy, state, or display behavior in one `frontend/src/views/` screen plus a matching test
- A backend validation or response-shaping fix in one route/service pair plus a route or service test
- A small operator script or config documentation update with a compose validation check

Avoid first changes that combine migrations, background tasks, frontend workflow rewrites, and external API behavior. Those are valid contributions, but they require more cross-system context.

For concrete patterns, use `docs/development/examples.md`. It includes backend routes, service tests, migrations, Celery tasks, Vue services/views, Pinia state, Playwright flows, docs updates, and PR descriptions.

For container-backed processing components, use `docs/development/first_hdp_component.md`.

For starter tasks, use `docs/development/good_first_changes.md`.

For a full first contribution path, use `docs/development/first_pr_walkthrough.md`.

If a local check fails, use `docs/development/troubleshooting_decision_tree.md`. If you are unsure which layer owns a behavior, use `docs/development/architecture_map.md`. If a project-specific term is unclear, use `docs/development/developer_glossary.md`. If a PR is growing too wide, use `docs/development/pr_scope_examples.md`. If a passing command prints concerning output, check `docs/development/known_warnings.md`.

## 4. Find The Right Files

- API endpoint: start in `routes/`, then follow the service call into `services/`.
- Business rule: start in `services/`, then check which routes and tasks call it.
- Database state: start in `database/models.py`, then check `migrations/versions/` and tests.
- Workflow UI: start in `frontend/src/router/index.js`, then the matching `frontend/src/views/` file, store, and service.
- Shared frontend API behavior: start in `frontend/src/services/`.
- Async processing: start in `tasks.py`, then move core logic into or inspect `services/`.
- HPC bridge: stay under `hpc-link/` unless a WebHDP route or client explicitly integrates with it.
- Product contract: check `docs/architecture/system_architecture.md`.
- `.hdpc` persistence: check `docs/architecture/hdpc_schema.md`.

## 5. Before You Open A Pull Request

1. Run the smallest relevant test command while developing.
2. Run the broader check for the area you touched before review.
3. Update docs for changed setup, API behavior, workflow state, feature flags, storage behavior, or operator responsibilities.
4. Compare your work with the relevant example in `docs/development/examples.md`.
5. Fill out `.github/pull_request_template.md`.
6. Explain any skipped check and why it was not practical locally.

## 6. Common Pitfalls

- Do not put reusable business rules directly in routes or Vue views.
- Do not rely on frontend route guards as the only permission check.
- Do not change persisted workflow state shapes without considering resumed sessions.
- Do not log or expose cleartext credentials, recovery codes, private paths, or raw tracebacks.
- Do not update `.env`; update `.env.example` when adding configuration.
- Do not add large sample assets unless the project owner explicitly approves the storage approach.

## 7. When You Are Unsure

Prefer a small draft pull request or issue comment that states:

- What behavior you want to change
- Which files you think own that behavior
- Which contract might be affected
- Which tests you plan to run

That gives maintainers enough context to steer the change before it grows in the wrong direction.
