# First Pull Request Walkthrough

Use this walkthrough for your first WebHDP contribution. It is intentionally small and repeatable: start from a tiny change, prove the environment, update the right docs or tests, and leave reviewers with a clear story.

## 1. Prove Your Workspace

Start with the health report:

```bash
make doctor
```

Read the output from top to bottom. `FAIL` means the workspace is not ready yet. `WARN` means the project can often still run, but the warning may block a fuller workflow such as Docker Compose or Devcontainers.

If the output is unclear, use `troubleshooting_decision_tree.md`.

Common remedies:

| Finding | Next command |
|---|---|
| Backend dependencies missing | `uv sync --group dev` |
| Frontend dependencies missing | `cd frontend && npm ci` |
| `.env` missing | `cp .env.example .env` |
| Docker daemon unavailable | Start Docker Desktop |
| Generated API contract stale | `make api-contract` |

If you use VS Code or Codespaces, the devcontainer runs the setup and onboarding checks for you. See `devcontainer.md`.

## 2. Pick A Tiny Change

For a first PR, choose one narrow behavior:

- clarify one paragraph in `docs/`
- add one missing command or troubleshooting note
- improve one frontend label plus the matching Vitest assertion
- add one backend validation branch plus a focused pytest
- expand one developer example without changing runtime behavior

Avoid combining unrelated surfaces in the first PR. A docs clarification should not also contain a migration. A frontend label should not also rewrite a Flask service. Small PRs make it easier for maintainers to review quickly and for you to learn the project rhythm.

## 3. Find The Owner

Use this map before editing:

For a deeper ownership map, use `architecture_map.md`. For unfamiliar project terms, use `developer_glossary.md`.

Before opening the PR, compare your change to `pr_scope_examples.md`. If your verification output contains warnings but the command passed, check `known_warnings.md` before spending time on unrelated noise.

| Change type | Start here | Usually test with |
|---|---|---|
| Developer docs | `docs/development/` | `make docs-check` |
| API route | `routes/` then `services/` | `uv run pytest tests/test_name.py -q` |
| Service rule | `services/` | service or route pytest |
| Database shape | `database/models.py`, `migrations/versions/` | migration-aware pytest |
| Frontend view | `frontend/src/views/` | `cd frontend && npm run test:unit -- testName` |
| Frontend API client | `frontend/src/services/` | service/view Vitest |
| Workflow contract | `docs/architecture/system_architecture.md` | focused backend and frontend tests |

When in doubt, search for the visible text, route path, service class, or test fixture:

```bash
rg "text or route you are changing"
rg "service_or_function_name"
```

## 4. Make The Change

Keep the first commit focused. Follow the nearby style instead of inventing a new pattern.

Backend example loop:

```bash
uv run pytest tests/test_developer_routes.py -q
```

Frontend example loop:

```bash
cd frontend
npm run test:unit -- developerModeView
```

Documentation example loop:

```bash
make docs-check
git diff --check
```

If you add, remove, or rename a Flask route, regenerate and check the OpenAPI inventory:

```bash
make api-contract
make api-contract-check
```

## 5. Run The Right Checks

Use the smallest loop while editing, then run the broader checks before opening the PR.

Minimum for every first PR:

```bash
make doctor
make verify-onboarding
```

Add area checks when relevant:

| Area touched | Extra check |
|---|---|
| Backend route or service | `uv run pytest tests/test_name.py -q` |
| Frontend view or service | `cd frontend && npm run test:unit -- testName` |
| Frontend build behavior | `cd frontend && npm run build` |
| Docker/Compose config | `make compose-check` |
| Devcontainer config | `make devcontainer-check` |
| Golden workflow fixtures | `make golden-workflow` |

If a check is impractical locally, say exactly why in the PR description and list the closest check you did run.

## 6. Write The PR Description

Use `.github/pull_request_template.md` and keep the description concrete:

```markdown
## Summary
- Added a first-PR walkthrough to developer onboarding.
- Linked it from the docs catalog and developer diagnostics.

## Verification
- make doctor
- make docs-check
- uv run pytest tests/test_developer_routes.py -q

## Notes
- No runtime behavior changed.
```

Good PR descriptions answer three reviewer questions:

- What changed?
- Why does this belong in WebHDP?
- How did you verify it?

## 7. Review Expectations

Maintainers primarily look for:

- behavior that matches the documented workflow contract
- clear ownership boundaries between routes, services, models, tasks, and frontend views
- tests near the changed behavior
- docs updated when setup, API behavior, permissions, workflow state, storage, or operator work changes
- no secret values, local paths, raw tokens, or private data in commits

Respond to review comments by either updating the PR or explaining the tradeoff. If a requested change would expand the PR beyond the original scope, it is usually better to open a follow-up issue.

## 8. After Merge

After your first PR lands, good next steps are:

- pick a starter task from `good_first_changes.md`
- copy a pattern from `examples.md`
- read one ADR in `adr/README.md`
- run the golden workflow again after pulling main

The goal is not to memorize the whole application. The goal is to learn one surface well, verify it carefully, and leave the next contributor a little more confident.
