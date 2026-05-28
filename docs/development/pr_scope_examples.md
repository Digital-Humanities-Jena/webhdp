# PR Size And Scope Examples

Use this page to decide whether a pull request is reviewable as one change or should be split. WebHDP crosses UI, API, background tasks, persistence, external services, and cultural-heritage metadata standards, so clear scope matters.

## 1. Healthy PR Shape

A good PR has:

- one clear user, operator, or developer outcome
- one primary owning layer
- tests near the changed behavior
- docs updates when setup, API, workflow, storage, permissions, or terminology changes
- a verification list that another contributor can rerun

Good summary:

```markdown
## Summary
- Added doctor output for stale frontend optional dependencies.
- Documented the fix in developer troubleshooting.

## Verification
- make doctor
- make docs-check
- uv run pytest tests/test_doctor.py -q
```

Risky summary:

```markdown
## Summary
- Improved onboarding.
- Refactored workflow services.
- Changed publish behavior.
- Updated UI.
```

The risky version may contain useful work, but it is too broad for one review because it mixes onboarding, workflow, publishing, and frontend behavior.

## 2. Good First PR Examples

| PR | Why it is good | Expected checks |
|---|---|---|
| Add a missing troubleshooting branch for `make doctor` | Docs-only, one owner, improves onboarding | `make docs-check`, `git diff --check` |
| Add one developer glossary term and link it from one doc | Small documentation improvement with clear discoverability | `make docs-check` |
| Add one route permission regression test | Narrow backend behavior, no UI churn | focused `uv run pytest tests/test_route.py -q` |
| Improve one frontend empty state label | One view, one assertion, no backend contract change | `cd frontend && npm run test:unit -- viewName` |
| Add one example to `examples.md` | Developer education only, no runtime behavior | `make docs-check` |
| Update Devcontainer docs after a config fix | Setup doc follows setup behavior | `make devcontainer-check`, `make docs-check` |

## 3. Good Medium PR Examples

| PR | Why it can stay together | Expected checks |
|---|---|---|
| Add a new read-only developer diagnostic field | Backend route, frontend display, tests, docs all serve one outcome | route pytest, view Vitest, `make docs-check` |
| Add a validation branch to one service and expose it in one route | Service rule and route response are one behavior | service/route pytest, API docs if response changes |
| Add a new docs catalog entry and docs hub test | Discoverability change is the outcome | docs check, frontend docs hub test |
| Add one generated OpenAPI route after adding one Flask endpoint | API behavior and contract inventory move together | route pytest, `make api-contract-check` |

## 4. Too Broad PR Examples

| PR shape | Why to split | Suggested split |
|---|---|---|
| New migration, new workflow state, frontend wizard rewrite, and publishing behavior change | Too many failure modes and reviewers | migration/model PR, backend workflow PR, frontend PR, docs PR |
| Zenodo credential refactor plus public record UI changes | Security-sensitive auth and public record UI need different review lenses | credential/security PR, public UI PR |
| Devcontainer changes plus unrelated route refactor | Setup verification noise can hide runtime regressions | onboarding PR, route PR |
| Large docs rewrite plus behavior changes | Reviewers cannot tell whether docs describe existing or new behavior | behavior PR with targeted docs, then docs cleanup PR |
| Formatting many files plus logic change | Diff noise obscures behavior | formatting-only PR, then logic PR |

## 5. Needs ADR Examples

Use an ADR when a change creates or changes a lasting architectural rule.

| Change | Why it needs an ADR |
|---|---|
| Changing the workflow state machine | Affects uploads, resumed sessions, UI guards, tasks, and docs |
| Moving record ownership from `.hdpc` to app DB or the reverse | Changes persistence boundaries |
| Changing credential resolution order | Security and publishing behavior depend on it |
| Making an optional integration required | Affects low-resource and offline deployments |
| Introducing a second frontend state persistence strategy | Changes resumed workflow behavior |
| Replacing a core metadata validation approach | Affects scientific output confidence |

ADR location:

```text
docs/development/adr/
```

## 6. Split Checklist

Split the PR if two or more are true:

- it changes both persistence and UI
- it changes auth/permissions and unrelated display behavior
- it modifies generated artifacts and hand-written docs without a single reason
- it touches more than one external integration
- it requires multiple unrelated verification commands
- it needs more than one reviewer specialty
- it contains a cleanup/refactor and a behavior change

Keep it together if:

- every file supports the same behavior
- tests tell one story
- docs explain the changed behavior directly
- rollback would be one decision

## 7. Review Description Patterns

Small docs PR:

```markdown
## Summary
- Clarified the Devcontainer dependency isolation behavior.

## Verification
- make docs-check
- git diff --check
```

Backend PR:

```markdown
## Summary
- Added a permission check for the developer diagnostics endpoint.
- Added regression coverage for regular users, developer capability users, and admins.

## Verification
- uv run pytest tests/test_developer_routes.py -q
- make api-contract-check
```

Cross-layer PR:

```markdown
## Summary
- Added one read-only developer onboarding link to the API response.
- Rendered the link in Developer Mode.
- Registered the doc in the in-app docs catalog.

## Verification
- uv run pytest tests/test_developer_routes.py -q
- cd frontend && npm run test:unit -- developerModeView documentationHubView
- make docs-check
```

## 8. What Maintainers Usually Ask

Expect review questions like:

- Which layer owns this behavior?
- What is the smallest test that proves it?
- Does this change an API, workflow, permission, or persistence contract?
- Does documentation describe the new behavior?
- Can this be split from cleanup?
- What happens in Devcontainer, Docker Compose, and host development?

Answer those questions in the PR description before reviewers have to ask them.
