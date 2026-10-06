# WebHDP Frontend

This is the Vue 3/Vite frontend for WebHDP. It provides the public landing and record pages, setup flow, authenticated workflow, dashboards, admin/settings surfaces, documentation hub, tools, and operator views.

## Stack

- Vue 3 with single-file components
- Vite 7
- Pinia for shared state
- Vue Router for public/authenticated/admin routes
- Axios-based service modules under `src/services/`
- Vitest for unit and integration tests
- Playwright for end-to-end browser flows

Use Node.js 22.12 or newer.

## Local Development

```bash
npm ci
npm run dev
```

The API base URL is normalized in `src/services/apiBase.js`. Check `.env.development` and `.env.production` before changing API roots.

For full-project onboarding, including backend setup and Docker, see `../docs/development/onboarding.md`. For copyable frontend service, view, store, and Playwright patterns, see `../docs/development/examples.md`.

## Common Commands

```bash
npm run test:unit
npm run build
npm run test:e2e
npm run test:e2e:headed
npm run test:e2e:core
npm run test:e2e:backend
```

The core browser suite exercises workflow guidance and recovery in Chromium and
Firefox with controlled API responses. The backend suite starts
`../tests/browser_api.py` with an isolated temporary database/workspace and uses
the real upload, metadata, readiness, execution, checkpoint and derivative routes.
It covers reload/lost acknowledgement, partial failure, selective continuation
and checksum-verified model comparison. Only external component execution and
delivery are replaced by deterministic fixtures; no Docker, Draco, Zenodo or
production database is required. Install the root Python development dependencies
and Playwright browsers before running it. Fixture routes exist only in that
test application.

If Vite configuration bundling stalls on a local setup, use
`npm run test:unit -- --configLoader runner` and
`npm run build -- --configLoader runner`. Both Playwright configurations use this
loader for their local development servers.

## Source Map

| Path | Purpose |
|---|---|
| `src/router/index.js` | Route table and route guards |
| `src/services/` | API clients and backend payload adapters |
| `src/stores/` | Pinia stores for auth, workflow, system, and notifications |
| `src/views/` | Route-level pages and workflow screens |
| `src/components/` | Reusable UI and domain components |
| `src/composables/` | Shared Vue composition helpers |
| `src/utils/` | Pure utilities and payload shaping helpers |
| `tests/` | Vitest unit/integration tests |
| `e2e/` | Playwright browser tests |

## Contribution Notes

- Put API calls in `src/services/` rather than directly in views.
- Put shared cross-view state in `src/stores/`; avoid using a store for one component's local state.
- Keep frontend route guards aligned with backend authorization checks.
- Be careful with `src/stores/workflow.js`: it persists workflow state in `sessionStorage`, so shape changes can affect resumed sessions.
- Add or update tests when changing stores, services, workflow sequencing, route guards, or user-visible state.

For the full repository contribution model, see `../docs/development/contributor_handbook.md`.
