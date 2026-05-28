# Known Development Warnings

This page lists warnings that new contributors may see while running local checks. A warning is not automatically safe; treat this page as a triage aid, not permission to ignore new failures.

Trust command exit codes first. If the command exits non-zero, debug the failure even if the warning text looks familiar.

## 1. Backend Test SQLAlchemy Warnings

You may see warnings like:

```text
SAWarning: relationship 'Session.publishing_user' will copy column users.id to column sessions.publishing_user_id...
```

You may also see:

```text
SAWarning: Can't sort tables for DROP; an unresolvable foreign key dependency exists...
```

Current status:

- These are known warnings in the current backend test harness.
- They do not make a passing pytest run fail.
- They usually appear when tests create and drop in-memory SQLite schemas.

Do not ignore them if:

- a related test is failing
- you changed `database/models.py`
- you changed publishing user relationships
- you changed institution/user foreign keys
- you added or modified migrations

Useful checks:

```bash
uv run pytest tests/test_developer_routes.py -q
uv run pytest tests/test_publishing_context_and_session_access.py -q
```

## 2. Frontend `--localstorage-file` Warning

You may see:

```text
Warning: `--localstorage-file` was provided without a valid path
```

Current status:

- This is known test-environment noise from the local Node/Vitest/browser storage setup.
- It does not make a passing Vitest run fail.

Do not ignore it if:

- tests that depend on browser storage are failing
- you changed workflow persistence
- you changed auth token storage
- you changed Vitest setup files

Useful checks:

```bash
cd frontend
npm run test:unit -- workflowState authStore routerGuards
```

## 3. Browserslist Data Warning

You may see:

```text
Browserslist: browsers data (caniuse-lite) is 6 months old.
```

Current status:

- This warning is common in frontend test/build output.
- It does not fail tests by itself.
- Updating Browserslist data can modify lockfile state, so do it intentionally as dependency maintenance.

Do not mix a Browserslist update into an unrelated feature PR unless maintainers asked for it.

## 4. npm Audit Warnings

`npm ci` may report:

```text
2 moderate severity vulnerabilities
```

Current status:

- This is known for the current frontend dependency tree.
- CI separately runs production dependency audits with configured thresholds.
- `npm audit fix --force` can introduce breaking dependency changes, so do not run it casually inside feature PRs.

Good handling:

- Mention audit output only if your PR changes dependencies.
- For dependency remediation, open a dedicated dependency-maintenance PR.
- Run frontend tests and build after any dependency update.

## 5. npm Deprecated Package Warnings

You may see deprecated transitive dependency warnings such as `glob`.

Current status:

- These warnings come from dependencies pulled by the current toolchain.
- They do not fail `npm ci` by themselves.

Do not chase them in unrelated PRs. If you update the dependency tree, keep that PR narrowly scoped.

## 6. uv Hardlink Warning In Containers

In containerized setups you may see:

```text
warning: Failed to hardlink files; falling back to full copy.
```

Current status:

- This can happen when the uv cache and target environment are on different filesystems.
- It is a performance warning, not a correctness failure.

The Devcontainer sets `UV_PROJECT_ENVIRONMENT=/home/vscode/.venv/webhdp` so Python packages do not replace the host `.venv`.

## 7. Devcontainer npm Output

During Devcontainer setup, `npm ci` can print audit and update notices. These are expected as long as:

- `postCreateCommand` exits successfully
- `make docs-check` passes
- `make api-contract-check` passes
- `make golden-workflow` passes

The Devcontainer mounts `frontend/node_modules` as a named Linux volume. This prevents Linux optional packages from overwriting host-machine `frontend/node_modules`.

## 8. Docker Image And BuildKit Noise

Docker and Devcontainer builds can print:

- image digest lines
- attestation manifest lines
- cached layer messages
- feature dependency resolution messages

Current status:

- These are normal BuildKit/Devcontainer messages.
- The important signal is the final outcome, such as `outcome: success` from the Devcontainer CLI or a zero exit code from `make devcontainer-check`.

## 9. When A Warning Is Not Known

Treat a warning as new if:

- it does not appear on this page
- it appears only after your change
- it references a file you edited
- it comes with a non-zero exit code
- it mentions secrets, permissions, migrations, data loss, or failed validation

For new warnings:

```bash
make doctor
git diff --check
```

Then run the smallest focused test for the area you touched.

## 10. When To Update This Page

Update this page when:

- a new harmless warning appears regularly in onboarding checks
- an old warning is fixed and should no longer be expected
- a warning becomes a failure due to stricter CI
- a common warning needs a better explanation for new contributors

Keep entries specific. Include the command, the warning shape, whether it is currently safe, and when it should be investigated.
