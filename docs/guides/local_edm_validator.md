# Local EDM Validator Integration

WebHDP uses [Digital-Humanities-Jena/local-edm-validator](https://github.com/Digital-Humanities-Jena/local-edm-validator) for EDM validation during template checks and LOD generation. The local validator replaces the slower remote METIS Sandbox API path for the active validation workflow while preserving compatibility aliases for older configuration names.

## What It Does

- Validates rendered EDM RDF/XML through the local `/record/validation` endpoint.
- Runs the fast local validation path and skips workflow parts that are not relevant for WebHDP template and LOD checks.
- Returns the full validation report, including every local validator step, messages, problem patterns, and timing data.
- Exposes health and build/source metadata through Spring Actuator:
  - `/actuator/health`
  - `/actuator/info`
- Persists validation evidence for generated LOD files:
  - `edm.validation.json` beside generated `edm.xml`
  - full validation report JSON in local `.hdpc` source-file metadata

## Runtime Paths

Template validation:

1. The admin edits or previews an EDM template.
2. WebHDP renders the template with sample or session metadata.
3. `EdmService` sends the rendered XML to `LocalEdmValidatorClient`.
4. The frontend displays structural status, warnings/errors, problem patterns, local validator steps, and elapsed time.

LOD generation:

1. Native pipeline LOD generation writes `edm.xml`.
2. WebHDP validates the generated XML with local-edm-validator when `ENABLE_LOCAL_EDM_VALIDATION=true`.
3. The pipeline writes `edm.validation.json`.
4. The local `.hdpc` `source_files` row for `edm.xml` stores the full report and first error message for audit and troubleshooting.

Admin status:

1. `GET /api/v1/admin/edm-validator/status` calls `/actuator/health` and `/actuator/info`.
2. Settings -> EDM Config shows enabled state, endpoint, reachability, response time, version, commit/source ref, build time, and image tag.

## Configuration

Core variables:

```bash
LOCAL_EDM_VALIDATOR_URL=http://host.docker.internal:18080
ENABLE_LOCAL_EDM_VALIDATION=true
LOCAL_EDM_VALIDATOR_REQUIRED=true
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true
EMIT_EUROPEANA_3D_ADVISORY_FIELDS=false
```

Use `http://localhost:18080` only when WebHDP itself runs directly on the host
instead of inside Docker. The managed Compose overlay sets
`LOCAL_EDM_VALIDATOR_URL=http://local-edm-validator:8080` for backend and worker
containers.

Managed Compose overlay variables:

```bash
LOCAL_EDM_VALIDATOR_REPO=./external_code/local-edm-validator
LOCAL_EDM_VALIDATOR_SOURCE_REPOSITORY=https://github.com/Digital-Humanities-Jena/local-edm-validator.git
LOCAL_EDM_VALIDATOR_SOURCE_REF=b1ba67802ae1581c88ba8ea0ae9740cf663a0176
LOCAL_EDM_VALIDATOR_IMAGE=local-edm-validator:webhdp-b1ba67802ae1
LOCAL_EDM_VALIDATOR_PORT=18080
```

Legacy compatibility:

- `ENABLE_METIS_VALIDATION`
- `METIS_SANDBOX_URL`
- `METIS_SANDBOX_API_URL`

These aliases remain supported for older deployments, but new deployments should use the `LOCAL_EDM_VALIDATOR_*` names.

## Managed Docker Compose Deployment

The managed overlay is `docker-compose.edm-validator.yml`. It starts:

- `local-edm-validator`
- PostgreSQL
- MongoDB
- Solr
- MinIO
- MinIO bucket initialization

Setup:

```bash
make local-edm-validator-setup
make local-edm-validator-verify
docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml up -d --build
```

The setup script checks out upstream commit
`b1ba67802ae1581c88ba8ea0ae9740cf663a0176` and applies the tracked WebHDP patch
`patches/local-edm-validator/webhdp-dockerfile-local.patch`. This keeps the
release reproducible without vendoring the upstream validator source.

Production deployments should use the same overlay with `docker-compose.prod.yml` or provide an equivalent always-on validator endpoint:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.edm-validator.yml up -d --build
```

The overlay routes backend and worker traffic to:

```text
http://local-edm-validator:8080
```

It also exposes the validator to the host at:

```text
http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}
```

The validator's upstream configuration expects dependency hostnames such as `metis-sandbox-postgres`, `metis-sandbox-mongo`, `metis-sandbox-solr`, and `metis-sandbox-minio`. The WebHDP overlay provides these names as Docker network aliases.

## Smoke Tests

Check the validator directly:

```bash
curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/health
curl http://localhost:${LOCAL_EDM_VALIDATOR_PORT:-18080}/actuator/info
```

Check from WebHDP:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/edm-validator/status"
```

Expected status response shape:

```json
{
  "success": true,
  "data": {
    "enabled": true,
    "url": "http://local-edm-validator:8080",
    "continue_on_error": true,
    "health": {
      "ok": true,
      "status": "UP",
      "response_time_millis": 18
    },
    "info": {
      "ok": true,
      "summary": {
        "version": "1.0.0-local",
        "repository": "https://github.com/Digital-Humanities-Jena/local-edm-validator",
        "source_ref": "b1ba678",
        "image_tag": "local-edm-validator:local",
        "git_commit_short": "b1ba678",
        "build_time": "2026-04-30T10:58:46.055Z"
      }
    }
  }
}
```

## Operational Notes

- Keep `LOCAL_EDM_VALIDATOR_SOURCE_REF` aligned with the pinned validator commit before building the image.
- Record the image tag and source ref in release notes when validation behavior changes.
- If `LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true`, the validator returns all available step results instead of stopping at the first failure.
- Keep `LOCAL_EDM_VALIDATOR_REQUIRED=true` in deployments. With required validation, EDM output is not considered successfully generated unless the local validator accepts it.
- Keep `EMIT_EUROPEANA_3D_ADVISORY_FIELDS=false` until the active local validator schema accepts the newer Europeana 3D advisory fields (`schema:digitalSourceType`, `edm:intendedUsage`, and 3D count properties). WebHDP still emits validator-compatible 3D identifiers such as `edm:type` and `dc:type`.
- `ENABLE_LOCAL_EDM_VALIDATION=false` is only for isolated developer troubleshooting; deployments should leave it enabled and run the managed validator overlay.
- The UI status card proves reachability and metadata visibility, but the strongest functional check is a template validation run from Settings -> EDM Templates.

## Troubleshooting

If Settings -> EDM Config reports unavailable:

1. Check `/actuator/health` from the host.
2. Check that backend/worker containers resolve `local-edm-validator`.
3. Confirm the overlay is active: `docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml config`.
4. Inspect validator dependency services and health checks.

If `/actuator/info` is empty or missing fields:

1. Confirm the validator image was built from a Git checkout, not a source archive without `.git`.
2. Run `make local-edm-validator-verify` before building.
3. Rebuild `local-edm-validator`.

If validation succeeds but report details are missing:

1. Confirm the response contains `validationResults` or equivalent local validator report fields.
2. Re-run template validation from Settings -> EDM Templates.
3. Check `edm.validation.json` beside generated `edm.xml` for native pipeline LOD runs.
