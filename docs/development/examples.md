# WebHDP Developer Examples

This cookbook shows practical contribution patterns for WebHDP. It complements `onboarding.md` and `contributor_handbook.md` by giving concrete examples you can adapt when adding or changing behavior.

The examples are intentionally written as patterns. Replace names, routes, fields, and tests with the actual feature you are building. Do not add an `example_*` feature to the product unless that is genuinely the requested feature.

## 1. How To Use These Examples

Before copying a pattern, answer four questions:

1. Which surface owns the behavior: route, service, task, model, frontend service, store, view, or documentation?
2. Which persisted contract can be affected: API response, session state, `.hdpc` schema, app DB schema, task progress, frontend storage, or public output?
3. Which tests prove the behavior: backend route/service, migration, frontend unit/integration, Playwright, or compose validation?
4. Which docs must change: API reference, architecture, operations guide, onboarding, or user guide?

Use the smallest example that matches your change. Most contributions should not require every layer shown here.

## 2. Example: Trace An Existing Feature Before Editing

When joining the project, first learn the current path of similar behavior.

```bash
rg -n "workspace-summary|provenance-report|zenodo-status" routes services frontend/src tests frontend/tests docs
```

Then follow one request through the layers:

1. Find the route in `routes/`.
2. Find the service call in `services/`.
3. Find any models in `database/models.py`.
4. Find frontend calls in `frontend/src/services/`.
5. Find views or stores that consume the payload.
6. Find tests with the same route or service name.
7. Check docs under `docs/api/`, `docs/architecture/`, or `docs/guides/`.

Example search path for a docs endpoint:

```bash
rg -n "docs/index|DocumentationHub|docsService" routes frontend/src frontend/tests tests docs
```

What good tracing produces:

- Route: `routes/docs_routes.py`
- Frontend service: `frontend/src/services/docs.service.js`
- View test: `frontend/tests/documentationHubView.spec.mjs`
- API response shape: `APIResponse.success(...)`

## 3. Example: Add A Backend Read Endpoint

Use this when adding a small authenticated read route that returns derived data.

### Files Usually Touched

- `routes/some_domain_routes.py`
- `services/some_domain_service.py`
- `tests/test_some_domain_routes.py`
- `docs/api/webhdp_api_reference.md` if integrator-facing

### Service Pattern

Keep business logic in the service. Return plain dictionaries that routes can serialize.

```python
# services/session_quality_service.py
from database.models import Session as DBSession, File as DBFile


class SessionQualityService:
    def build_summary(self, session_id: int) -> dict:
        session = DBSession.query.get(session_id)
        if session is None:
            return {"found": False}

        files = DBFile.query.filter_by(session_id=session_id).all()
        failed_count = sum(1 for item in files if item.status == "failed")

        return {
            "found": True,
            "session_id": session.id,
            "status": session.status,
            "file_count": len(files),
            "failed_file_count": failed_count,
            "ready_for_submit": session.status == "scanned" and failed_count == 0,
        }
```

Why this shape helps:

- It is easy to test without a request context.
- It returns explicit booleans instead of making the frontend infer readiness.
- It does not expose local paths or private fields.

### Route Pattern

The route should handle HTTP details, auth, ownership, and response formatting.

```python
# routes/session_routes.py
from api_utils import APIResponse
from services.session_quality_service import SessionQualityService


@session_bp.route("/<int:session_id>/quality-summary", methods=["GET"])
@jwt_required()
def get_session_quality_summary(session_id):
    session = require_session(session_id)
    if session is None:
        return APIResponse.not_found("Session not found")

    summary = SessionQualityService().build_summary(session_id)
    if not summary.get("found"):
        return APIResponse.not_found("Session not found")

    return APIResponse.success({"summary": summary})
```

Best practices:

- Reuse existing access helpers such as `require_session` or route-local ownership checks.
- Keep the endpoint name specific. Avoid vague routes like `/status` when the domain already has several statuses.
- Return a stable object under a named key such as `summary`, `record`, `operation`, or `items`.

### Test Pattern

For many route tests, this repo uses a small in-memory Flask app and registers the blueprint under a test prefix.

```python
# tests/test_session_quality_routes.py
import unittest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from routes.session_routes import session_bp


class TestSessionQualityRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "jwt-test-secret"

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(session_bp, url_prefix="/sessions")

        with self.app.app_context():
            db.create_all()
            self.user = User(email="user@example.com", role=UserRole.USER)
            self.user.set_password("password")
            db.session.add(self.user)
            db.session.commit()
            self.token = create_access_token(identity=str(self.user.id))

            self.session = DBSession(user_id=self.user.id, status="scanned", session_dir="/tmp/test")
            db.session.add(self.session)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_quality_summary_requires_auth(self):
        with self.app.test_client() as client:
            response = client.get(f"/sessions/{self.session.id}/quality-summary")
        self.assertEqual(response.status_code, 401)

    def test_quality_summary_returns_session_readiness(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        with self.app.test_client() as client:
            response = client.get(f"/sessions/{self.session.id}/quality-summary", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["summary"]["status"], "scanned")
```

Add negative tests for:

- Missing auth
- Wrong owner or insufficient role
- Missing resource
- Invalid request payload

## 4. Example: Add A Backend Write Endpoint

Use this when an endpoint mutates state. Write endpoints need stronger validation and tests than read endpoints.

### Schema Pattern

Use Pydantic schemas for non-trivial payloads.

```python
# schemas/session_schemas.py
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionLabelUpdateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(..., min_length=1, max_length=120)

    @field_validator("label")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Label cannot contain control characters")
        return value
```

### Route Pattern

```python
from pydantic import ValidationError as PydanticValidationError
from flask import request

from api_utils import APIResponse
from database.database import db
from schemas.session_schemas import SessionLabelUpdateSchema


@session_bp.route("/<int:session_id>/label", methods=["PATCH"])
@jwt_required()
def update_session_label(session_id):
    session = require_session(session_id)
    if session is None:
        return APIResponse.not_found("Session not found")

    try:
        payload = SessionLabelUpdateSchema.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        return APIResponse.validation_error("Invalid session label", details={"errors": exc.errors()})

    session.label = payload.label
    db.session.commit()
    return APIResponse.success({"session_id": session.id, "label": session.label})
```

Write endpoint checklist:

- Validate every client-controlled field.
- Check ownership and role before mutation.
- Commit once after a complete valid mutation.
- Roll back on exceptions if the route catches them.
- Avoid partial state transitions unless the workflow contract explicitly allows them.
- Add tests for invalid input and unauthorized users.

## 5. Example: Add A Database Field And Migration

Use this when persistent app state changes. `.hdpc` schema changes are separate and must follow `docs/architecture/hdpc_schema.md`.

### Model Change Pattern

```python
# database/models.py
class Session(db.Model):
    __tablename__ = "sessions"

    # existing columns...
    label = db.Column(db.String(120), nullable=True)
```

### Migration Pattern

Create an Alembic revision and keep it deterministic.

```bash
uv run flask --app app db revision -m "add session label"
```

Then edit the generated file:

```python
"""add session label

Revision ID: 1234abcd5678
Revises: previous_revision_id
Create Date: 2026-05-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1234abcd5678"
down_revision = "previous_revision_id"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("label")
```

Migration best practices:

- Prefer nullable/additive fields unless a backfill is part of the same migration.
- Use `batch_alter_table` for SQLite compatibility.
- Do not delete user data unless the change explicitly requires it and the PR explains it.
- Update serializers and API docs when a new field becomes visible to clients.

## 6. Example: Add A Celery Task

Use this when a process can be slow, retried, scheduled, or monitored by users/operators.

### Service First

```python
# services/session_cleanup_preview_service.py
from database.models import Session as DBSession


class SessionCleanupPreviewService:
    def build_preview(self, older_than_days: int) -> dict:
        candidates = DBSession.query.filter(DBSession.status.in_(["completed", "failed"])).all()
        return {
            "older_than_days": older_than_days,
            "candidate_count": len(candidates),
            "session_ids": [session.id for session in candidates],
        }
```

### Task Wrapper

```python
# tasks.py
from celery_app import celery
from services.session_cleanup_preview_service import SessionCleanupPreviewService


@celery.task(bind=True)
def build_session_cleanup_preview_task(self, older_than_days=30):
    self.update_state(
        state="PROGRESS",
        meta={"current_stage": "collecting", "percent": 10},
    )
    preview = SessionCleanupPreviewService().build_preview(older_than_days)
    self.update_state(
        state="PROGRESS",
        meta={"current_stage": "completed", "percent": 100},
    )
    return {"status": "completed", "preview": preview}
```

Task best practices:

- Keep core logic outside the task for easier tests.
- Persist progress if the UI needs to resume or poll after refresh.
- Include stable stage names and counts.
- Make failures explicit and safe for operators.
- Never include tokens, passwords, or private file contents in task metadata.

### Route Launch Pattern

```python
@tools_bp.route("/cleanup-preview", methods=["POST"])
@jwt_required()
def launch_cleanup_preview():
    # Also check admin/moderator role if this affects operator workflows.
    task = build_session_cleanup_preview_task.delay(30)
    return APIResponse.accepted({"task_id": task.id}, message="Cleanup preview started")
```

## 7. Example: Add A Frontend API Service Method

Use service modules to centralize backend calls.

```javascript
// frontend/src/services/sessionQuality.service.js
import api from './api'

const sessionQualityService = {
  getSummary(sessionId) {
    return api.get(`/sessions/${encodeURIComponent(sessionId)}/quality-summary`)
  },
}

export default sessionQualityService
```

Best practices:

- Use `encodeURIComponent` for path values that are not guaranteed integers.
- Keep response normalization here when multiple views need it.
- Use `{ suppressGlobalError: true }` only when the view will render a local error state.
- Do not store tokens manually here; `src/services/api.js` attaches auth headers.

### Frontend Service Test Pattern

Pure helper modules are easy to test directly. Service modules that call Axios are often tested through view tests or with mocks.

```javascript
// frontend/tests/sessionQuality.service.spec.mjs
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  default: mocked.api,
}))

import sessionQualityService from '../src/services/sessionQuality.service.js'

describe('sessionQualityService', () => {
  beforeEach(() => {
    mocked.api.get.mockReset()
  })

  it('loads a session quality summary', async () => {
    mocked.api.get.mockResolvedValue({ data: { summary: { ready_for_submit: true } } })

    const result = await sessionQualityService.getSummary(41)

    expect(mocked.api.get).toHaveBeenCalledWith('/sessions/41/quality-summary')
    expect(result.data.summary.ready_for_submit).toBe(true)
  })
})
```

## 8. Example: Add A Vue View That Loads Data

Use this for dashboard/admin/tool pages that fetch data and render loading, success, and error states.

```vue
<!-- frontend/src/views/tools/SessionQualityView.vue -->
<template>
  <section class="space-y-4">
    <header>
      <h1>Session Quality</h1>
    </header>

    <LoadingSpinner v-if="isLoading" text="Loading session quality" />

    <Alert v-else-if="errorMessage" type="error" :message="errorMessage" />

    <dl v-else-if="summary">
      <dt>Status</dt>
      <dd>{{ summary.status }}</dd>
      <dt>Files</dt>
      <dd>{{ summary.file_count }}</dd>
    </dl>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import Alert from '@/components/ui/Alert.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import sessionQualityService from '@/services/sessionQuality.service'

const route = useRoute()
const isLoading = ref(false)
const errorMessage = ref('')
const summary = ref(null)

async function loadSummary() {
  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await sessionQualityService.getSummary(route.params.sessionId)
    summary.value = response.data.summary
  } catch (error) {
    errorMessage.value = error?.error?.message || error?.message || 'Unable to load session quality.'
  } finally {
    isLoading.value = false
  }
}

onMounted(loadSummary)
</script>
```

View best practices:

- Use local loading and error states for page-specific data.
- Keep API calls in services, not inline Axios calls.
- Keep long-lived cross-view state in Pinia stores only when more than one view needs it.
- Use stable selectors or accessible names when Playwright tests will interact with the view.

### View Test Pattern

```javascript
// frontend/tests/sessionQualityView.spec.mjs
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mountWithApp } from './helpers/app.mjs'

const mocked = vi.hoisted(() => ({
  service: {
    getSummary: vi.fn(),
  },
}))

vi.mock('@/services/sessionQuality.service', () => ({
  default: mocked.service,
}))

import SessionQualityView from '../src/views/tools/SessionQualityView.vue'

describe('SessionQualityView', () => {
  beforeEach(() => {
    mocked.service.getSummary.mockReset()
  })

  it('renders the loaded summary', async () => {
    mocked.service.getSummary.mockResolvedValue({
      data: {
        summary: {
          status: 'scanned',
          file_count: 2,
        },
      },
    })

    const { wrapper } = await mountWithApp(SessionQualityView, {
      route: '/tools/session-quality/41',
      routes: [{ path: '/tools/session-quality/:sessionId', component: SessionQualityView }],
    })
    await flushPromises()

    expect(mocked.service.getSummary).toHaveBeenCalledWith('41')
    expect(wrapper.text()).toContain('scanned')
    expect(wrapper.text()).toContain('2')
  })
})
```

## 9. Example: Add A Pinia Store Field Safely

Use a store only for cross-view state or state that must survive route changes.

When changing `frontend/src/stores/workflow.js`, remember that it persists to `sessionStorage`. New fields should have defaults in both the initial state and reset path.

```javascript
const getInitialState = () => {
  const stored = sessionStorage.getItem('workflowState')
  if (stored) {
    try {
      return JSON.parse(stored)
    } catch (e) {
      console.error('Failed to parse workflow state, resetting.', e)
    }
  }

  return {
    currentStep: 1,
    sessionId: null,
    qualitySummary: null,
  }
}
```

Add the ref, setter, reset behavior, persisted shape, and return value:

```javascript
const qualitySummary = ref(initialState.qualitySummary || null)

function setQualitySummary(value) {
  qualitySummary.value = value || null
}

function resetWorkflow() {
  qualitySummary.value = null
}

const stateToPersist = computed(() => ({
  qualitySummary: qualitySummary.value,
}))

return {
  qualitySummary,
  setQualitySummary,
}
```

Store checklist:

- Can the data stay local to one view? If yes, do not add it to a store.
- Does persisted state need migration logic for older stored payloads?
- Does `resetWorkflow()` clear the new field?
- Do tests cover persistence and reset behavior?

## 10. Example: Add A Route To The Vue Router

Use route metadata to align frontend access with backend access.

```javascript
{
  path: 'tools/session-quality/:sessionId',
  name: 'SessionQuality',
  component: () => import('@/views/tools/SessionQualityView.vue'),
  meta: { requiresAuth: true },
}
```

For admin-only pages:

```javascript
{
  path: 'settings/example',
  name: 'ExampleAdminSetting',
  component: () => import('@/views/admin/ExampleAdminSettingView.vue'),
  meta: { requiresAdmin: true },
}
```

Best practices:

- Frontend route guards are user-experience helpers. Backend routes must still enforce authorization.
- Keep public routes explicit with `meta: { publicRoute: true }`.
- Add route guard tests when changing guard behavior, redirects, roles, or setup flow.

## 11. Example: Add A Playwright Browser Flow

Use Playwright when behavior depends on actual browser navigation, file inputs, storage, route guards, or modals.

```typescript
// frontend/e2e/session-quality.spec.ts
import { expect, test } from '@playwright/test'

import { apiV1, fulfillJson, loginThroughUi, mockLogin, mockSetupStatus } from './support/api'

test('shows a session quality summary', async ({ page }) => {
  await mockSetupStatus(page, true)
  await mockLogin(page)

  await page.route(apiV1('/sessions/41/quality-summary'), async (route) => {
    await fulfillJson(route, {
      data: {
        summary: {
          status: 'scanned',
          file_count: 2,
          ready_for_submit: true,
        },
      },
    })
  })

  await loginThroughUi(page)
  await page.goto('/tools/session-quality/41')

  await expect(page.getByRole('heading', { name: 'Session Quality' })).toBeVisible()
  await expect(page.getByText('scanned')).toBeVisible()
})
```

Playwright best practices:

- Mock backend APIs unless the goal is a live end-to-end smoke test.
- Prefer roles, labels, and test IDs over brittle CSS selectors.
- Assert the URL when testing navigation.
- Add failure-path tests for important workflows.

## 12. Example: Update API Documentation

When adding an integrator-facing endpoint, add an entry to `docs/api/webhdp_api_reference.md`.

````markdown
### GET /api/v1/sessions/{session_id}/quality-summary

Returns a read-only quality summary for a session the authenticated user can access.

Auth: required.

Response:

```json
{
  "success": true,
  "data": {
    "summary": {
      "session_id": 41,
      "status": "scanned",
      "file_count": 2,
      "failed_file_count": 0,
      "ready_for_submit": true
    }
  },
  "message": null,
  "metadata": {}
}
```
````

Also update examples if the endpoint is something integrators will call directly:

- `docs/api/webhdp_api_examples.md`
- `docs/guides/operations_and_setup_guide.md` for operator behavior
- `docs/architecture/system_architecture.md` for workflow contract changes

## 13. Example: Update Environment Configuration

When adding configuration:

1. Add the default in `config.py`.
2. Add the placeholder or documented value in `.env.example`.
3. Add compose wiring if the value is needed inside containers.
4. Add production validation if the value is required for secure production.
5. Document the variable in the relevant operator guide.

Example config pattern:

```python
# config.py
FEATURE_EXAMPLE_ENABLED = os.environ.get("FEATURE_EXAMPLE_ENABLED", "false").lower() in [
    "true",
    "on",
    "1",
    "yes",
]
```

Example `.env.example` entry:

```dotenv
# Enable the example feature for local development only.
FEATURE_EXAMPLE_ENABLED=false
```

Best practices:

- Development defaults should be safe and low-surprise.
- Production-required secrets should fail fast if missing or placeholder.
- Do not document real credentials or tokens.
- Prefer explicit feature flags for optional external integrations.

## 14. Example: Add Or Change Docker Compose Wiring

Use this when a service needs a new environment variable, volume, port, or dependency.

```yaml
services:
  backend:
    environment:
      - FEATURE_EXAMPLE_ENABLED=${FEATURE_EXAMPLE_ENABLED:-false}
    depends_on:
      redis:
        condition: service_healthy
```

Validation commands:

```bash
cp .env.example .env
docker compose config --quiet
docker compose -f docker-compose.prod.yml config --quiet
```

Compose best practices:

- Keep development and production overlays separate.
- Use health checks for services other services depend on.
- Use explicit resource limits for optional heavyweight processors.
- Avoid binding host secrets as writable volumes.

## 15. Example: Add Documentation To The In-App Docs Catalog

If a new document should appear inside WebHDP's Documentation Hub, add it to the catalog in `routes/docs_routes.py`.

```python
DocEntry(
    doc_id="developer-onboarding",
    title="Developer Onboarding",
    category="development",
    audience="developer",
    description="First-hour setup, contribution tracks, and first-change guidance.",
    rel_path="development/onboarding.md",
),
```

Checklist:

- `doc_id` is stable and URL-safe.
- `rel_path` stays inside `docs/`.
- The document renders as Markdown without relying on external private assets.
- Add or update a frontend docs hub test when default landing behavior or filtering changes.

## 16. Example: Security Review For A Contribution

Use this mini-review before opening a PR that touches auth, credentials, public pages, uploads, file paths, cloud storage, HPC, or external APIs.

```markdown
Security notes:
- Auth required: yes, JWT route guard plus backend ownership check.
- Roles: admin only for configuration mutation.
- Secrets: no token or recovery code appears in response, logs, task metadata, or tests.
- Paths: user-provided paths pass existing safe path validation.
- Public data: endpoint returns only published/public fields.
- Failure behavior: user sees a generic error; logs include request context but not private payloads.
```

Common red flags:

- Returning a model's full `to_dict()` from a public route without checking fields.
- Logging request JSON for credential, upload, or profile routes.
- Trusting a frontend route guard without a backend check.
- Extracting ZIP files without `safe_extract_zip`.
- Adding a config variable to `.env` but not `.env.example`.

## 17. Example: Pull Request Description

Use the PR template and keep it concrete.

```markdown
## Summary

- What changed: Added session quality summary endpoint and frontend read-only panel.
- Why it changed: Curators need to see whether a scanned session is ready to submit before starting the pipeline.

## Surfaces Changed

- [x] Backend API/routes
- [x] Backend services/tasks
- [ ] Database models/migrations
- [x] Frontend services/stores/views
- [ ] HPC Link
- [ ] Docker/deployment/config
- [x] Documentation only

## Verification

- [x] Backend tests: `uv run pytest tests/test_session_quality_routes.py`
- [x] Frontend unit tests: `cd frontend && npm run test:unit`
- [x] Frontend build: `cd frontend && npm run build`
- [ ] Not applicable; explain below

## Notes For Reviewers

- Migrations, environment variables, feature flags, or deployment steps: none.
- Security/privacy considerations: endpoint uses existing session ownership checks and returns no local paths.
- Known follow-up work: add Playwright coverage once the panel is linked from the dashboard.
```

Good PR descriptions name the changed contract and the checks. They do not force reviewers to infer risk from the diff alone.

## 18. Example: Debug A Failing Test

Start narrow, then widen.

```bash
uv run pytest tests/test_session_quality_routes.py -q
uv run pytest tests/test_session_quality_routes.py::TestSessionQualityRoutes::test_quality_summary_returns_session_readiness -q
```

For frontend:

```bash
cd frontend
npm run test:unit -- sessionQualityView
```

For Playwright:

```bash
cd frontend
npm run test:e2e -- session-quality.spec.ts --headed
```

Debugging checklist:

- Does the test initialize required app services on `self.app`?
- Does the route prefix in the test match the registered blueprint?
- Does the JWT identity type match existing route expectations?
- Did you mock the frontend service before importing the view?
- Does a persisted store value from a previous test need clearing?
- Does the mocked API response match WebHDP's `{ success, data, message, metadata }` shape?

## 19. Example: Decide Whether Docs Must Change

Docs should change when any answer below is yes:

| Question | Documentation To Update |
|---|---|
| Does setup require a new command, service, variable, volume, or credential? | `README.md`, `.env.example`, `docs/guides/operations_and_setup_guide.md` |
| Does an API endpoint change? | `docs/api/webhdp_api_reference.md`, `docs/api/webhdp_api_examples.md` |
| Does workflow state or record lifecycle change? | `docs/architecture/system_architecture.md`, user/operator guides |
| Does `.hdpc` persistence change? | `docs/architecture/hdpc_schema.md` |
| Does a user workflow screen change materially? | `docs/guides/end_to_end_user_guide.md` or the relevant `docs/guides/video_guides/` walkthrough page |
| Does contributor process change? | `CONTRIBUTING.md`, `docs/development/onboarding.md`, this examples file |
| Does a route change? | Regenerate `docs/api/openapi.json` with `make api-contract` |

If you are unsure, add a short docs note. Future contributors will thank you.

## 20. End-To-End Change Checklist

For a typical full-stack feature:

1. Trace a similar feature with `rg`.
2. Add or update backend service logic.
3. Add or update the route.
4. Add validation schema if the request body is non-trivial.
5. Add or update backend tests.
6. Add frontend service method.
7. Add or update store only if state must be shared or persisted.
8. Add or update the Vue view/component.
9. Add or update frontend tests.
10. Add Playwright coverage if the browser workflow changed.
11. Update API, architecture, operator, or user docs as needed.
12. Run relevant checks.
13. Fill out the PR template with risks and skipped checks.

That is the standard WebHDP contribution loop.
