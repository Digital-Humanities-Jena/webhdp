# Troubleshooting Guide

## 1. Setup and Connectivity

### Symptom
Setup check reports Zenodo unreachable or invalid key.

Likely causes:
- Missing/incorrect `ZENODO_SANDBOX_API_KEY` or `ZENODO_API_KEY`
- Network egress restrictions

Actions:
1. Verify environment variables are present in container runtime.
2. Re-run `POST /api/v1/setup/check`.
3. Test external connectivity from host/container.

### Symptom
Renderer check fails.

Likely causes:
- `fast-renderer` service not running
- Disabled intentionally via feature flag/profile

Actions:
1. Confirm service status and URL.
2. Check `ENABLE_RENDERER` flag.
3. In low-resource mode, confirm pipeline expectations are adjusted.

## 2. Ingestion and Session Issues

### Symptom
`/sessions/directory` returns cloud storage unavailable.

Likely causes:
- `pure_cloud` or `cloud_backup` mode active but providers are not reachable.

Actions:
1. Check `/api/v1/admin/storage-status`.
2. Validate provider credentials.
3. Switch mode temporarily to `server_only` if operationally acceptable.

### Symptom
MSF validation fails due to unmatched files.

Likely causes:
- Filename column mismatch
- File naming inconsistencies
- Hidden extensions/casing differences

Actions:
1. Use `/api/v1/msf/detect-filename-column`.
2. Validate with `/api/v1/msf/validate` before full session start.
3. Normalize naming conventions in source files or MSF.

## 3. Metadata and Validation

### Symptom
Saving user metadata fails validation.

Likely causes:
- Missing required fields (`upload_type`, `publication_date`, etc.)
- Invalid controlled vocab values

Actions:
1. Inspect validation error list from response.
2. Ensure required fields are populated and correctly typed.
3. Retry save after correcting payload.

### Symptom
Template validation reports XSD/Schematron/business-rule errors.

Likely causes:
- Incomplete or semantically inconsistent template/metadata mapping

Actions:
1. Use `/api/v1/templates/preview` for iterative debugging.
2. Re-run `/api/v1/templates/validate`.
3. Verify mapping assumptions against the official EDM guidance linked from `../standards_links.md`.

### Symptom
Settings -> EDM Config reports the local EDM validator as unavailable.

Likely causes:
- `local-edm-validator` container or external validator process is not running
- Backend is pointing at the wrong `LOCAL_EDM_VALIDATOR_URL`
- Managed Compose overlay was started without validator dependency services
- Validator is reachable but still starting PostgreSQL, MongoDB, Solr, or MinIO-backed components

Actions:
1. Check `curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/health`.
2. Check `curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/info` for version/source metadata.
3. Verify the active Compose overlay with `docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml config`.
4. Confirm backend/worker containers use `LOCAL_EDM_VALIDATOR_URL=http://local-edm-validator:8080` when the managed overlay is active.
5. See `local_edm_validator.md` for the full runbook.

### Symptom
EDM validation passes, but audit details or local validator steps are missing.

Likely causes:
- The validator response does not include the full local report fields.
- The pipeline did not write or register `edm.validation.json`.
- `.hdpc` source-file metadata was created before validation report persistence was enabled.

Actions:
1. Re-run validation from Settings -> EDM Templates and confirm the Validation tab shows Local Validator Steps.
2. For native pipeline output, check for `edm.validation.json` beside `edm.xml`.
3. Inspect the local `.hdpc` `source_files.validation_report_json` value for the generated `edm.xml` row.

## 4. Pipeline Execution and Progress

### Symptom
Submission stays in `processing` with no visible movement.

Likely causes:
- Celery worker unavailable
- Redis connectivity issue
- External dependency timeout

Actions:
1. Verify `worker` and `redis` containers.
2. Poll `/api/v1/submissions/<submission_id>/progress` and `/api/v1/sessions/tasks/<task_id>`.
3. Inspect worker and backend logs.

### Symptom
Submission fails with converter warnings/errors.

Likely causes:
- Unsupported or malformed source geometry
- Missing sidecar assets

Actions:
1. Review warning payload in progress/result.
2. Re-run with `abort_on_critical_error=false` to continue non-blocking processing.
3. Validate source asset integrity before retry.

## 5. Provenance and Record Retrieval

### Symptom
Session records endpoint reports source unavailable.

Likely causes:
- Session `.hdpc` file missing or not mounted on current backend instance

Actions:
1. Verify session storage mount and `SHARED_SESSION_PATH` mapping.
2. Confirm `.hdpc` file exists for the session.
3. Use warning details from response (`source_state`) for targeted recovery.

### Symptom
Zenodo Account Retrieval shows `PROGRESS`, but no retrieval worker is running.

Likely causes:
- Host network connection was lost.
- Terminal or worker process was interrupted.
- Backend process stopped after persisting a checkpoint but before marking the job failed or paused.

Actions:
1. Confirm no retrieval worker is still running.
2. Open Tools -> Zenodo Account Retrieval.
3. Resume the same retrieval ID instead of starting a new job.
4. Verify that pending windows decrease and that the generated shard count remains consistent.

Resume uses the persisted checkpoint, dedupe state, and manifest. Already generated `.hdpc` shards should remain valid and should not be deleted unless the user explicitly deletes the retrieval job.

### Symptom
Zenodo Account Retrieval progresses slowly with a high duplicate-skipped count.

Likely causes:
- A dense date window was split after some pages had already been harvested.
- A retrieval resumed from a checkpoint and rechecked overlapping pages.

Actions:
1. Treat duplicate-skipped growth as expected after dense-window splitting or resume.
2. Monitor pending windows, split count, and active window instead of only retrieved-record count.
3. Continue the retrieval unless the error field is populated or pending windows stop changing.

### Symptom
Saving Zenodo Account Retrieval retention or incremental schedule settings fails in the browser.

Likely causes:
- The frontend and backend are served from different origins.
- Backend CORS preflight does not allow `PATCH`.

Actions:
1. Confirm the backend response to an `OPTIONS` preflight includes `PATCH` in `Access-Control-Allow-Methods`.
2. Retry the save from Tools -> Zenodo Account Retrieval after updating CORS configuration or deployment settings.
3. Use the browser network panel or backend logs to distinguish CORS preflight failures from validation errors returned by the API.

## 6. HDP Component Installation

### Symptom
Local Docker component validation reports the image is not ready.

Likely causes:
- Docker CLI is not reachable from the WebHDP backend or worker process.
- The image has not been built or pulled on that machine.
- `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST` does not permit the image name.
- `WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES=true` is enabled and the image uses a tag instead of `@sha256:...`.

Actions:
1. Run `docker image inspect <image>` from the same host/context as the backend or worker.
2. Check `.env` for `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST` and digest pinning.
3. Rebuild or pull the image, then validate again in Tools -> HDP Component Installer.

### Symptom
Local Docker smoke test fails after installation.

Likely causes:
- The component does not implement the WebHDP request/response contract.
- `install.test.inputs` references a file not listed in `install.test.files`.
- The container requires network access during the smoke test.

Actions:
1. Validate the manifest with `uv run python scripts/validate_hdp_components.py <component> --strict-warnings`.
2. Inspect the smoke-test result logs and response JSON in the installer.
3. Keep smoke-test fixtures small and self-contained; local smoke tests run with `--network none`.

### Symptom
An HPC SIF installation validates but the smoke test fails.

Likely causes:
- HPC-Link can reach the SIF but the component entrypoint fails at runtime.
- `hpc.test` does not match the component's expected inputs.
- Remote Singularity/Apptainer runtime or bind paths differ from local assumptions.

Actions:
1. Inspect the HPC-Link test logs from the installer response.
2. Confirm `hpc.test.files`, `hpc.test.inputs`, and parameters match the component contract.
3. Retry when the target HPC is available; do not run acceptance tests against Draco while production jobs are active.

## 7. Access and Authorization

### Symptom
Admin endpoints return forbidden.

Likely causes:
- User role is not `admin` or `moderator` (where required)

Actions:
1. Check current user role via `/api/v1/auth/me`.
2. Update role via admin role endpoint if governance permits.

## 8. Logging and Incident Data Collection
When escalating incidents, collect:
- `logs/app.log`
- `logs/error.log`
- Request payload (excluding secrets)
- Submission/session IDs
- Task IDs and progress snapshots

## 9. Recovery Strategy
1. Reproduce in sandbox mode.
2. Fix root cause and rerun affected stage.
3. Verify with session-level provenance report.
4. Document remediation in operational notes.
