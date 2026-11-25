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

1. The admin requests validation of an EDM template.
2. WebHDP renders the template with sample or session metadata.
3. WebHDP runs its built-in checks and sends the rendered XML to `LocalEdmValidatorClient` when either validator flag is true.
4. The frontend displays structural status, warnings/errors, problem patterns, local validator steps, and elapsed time.

LOD generation:

1. Native pipeline LOD generation renders the EDM attachment when that format is enabled and a Zenodo draft is available.
2. For new EDM output, WebHDP calls local-edm-validator when `ENABLE_LOCAL_EDM_VALIDATION` or `LOCAL_EDM_VALIDATOR_REQUIRED` is true. A retry can reuse an intact artifact validated with the current XSD release.
3. The pipeline records validation evidence and writes `edm.xml` only after the requested checks pass.
4. The local `.hdpc` `source_files` row for `edm.xml` stores the full report and first error message for audit and troubleshooting.

Admin status:

1. `GET /api/v1/admin/edm-validator/status` calls `/actuator/health` and `/actuator/info`.
2. Settings -> EDM Config shows the configured enable flag, endpoint, reachability, response time, version, commit/source ref, build time, and image tag. The admin status API probes the endpoint even when workflow validation is disabled and returns the required flag separately.

The same flags govern explicit template validation, EDM mapping tests, and session EDM validation samples. A render-only template preview does not call the standalone validator. The administrator's local-storage Tools output preview calls it only on explicit request. When both flags are false, normal EDM checks still run XML, XSD, and business validation in WebHDP. Schematron runs in the standalone validator only. When requested, a rejected or unavailable standalone check prevents successful generation of new EDM output.

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
LOCAL_EDM_VALIDATOR_SOURCE_REF=a7b3ad461e6d35de7d8f5cee5531a43768d2e158
LOCAL_EDM_VALIDATOR_IMAGE=local-edm-validator:webhdp-a7b3ad461e6d-edm-20260720
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

The setup script checks out validator commit `a7b3ad461e6d35de7d8f5cee5531a43768d2e158`
and initializes its Metis Schema `v15` submodule at `a1201cd7e6be618bec67f8258348d8bddb93059b`.
The build uses that source for the first XSD pass and for the RDF bindings
used by problem-pattern analysis. Run setup again before rebuilding an existing
validator checkout. For Singularity, rebuild the validator image and regenerate
any optional FFmpeg-patched `app.jar` from the updated image.

The validator pins Europeana's 2026-07-20 Metis schema archive, the
2026-06-30 sorter and the default Metis Framework `v18` transformation.
The archive matches the current archive on Europeana's download server and
the schema files in Metis Schema `v15`. [Europeana schema archives](http://ftp.eanadev.org/schema_zips/) · [Metis Schema v15](https://github.com/europeana/metis-schema/tree/v15/src/main/resources/schema_xsds) · [Metis Framework v18](https://github.com/europeana/metis-framework/releases/tag/v18)

The validator reads both complete schema entries, including their root XSD
and Schematron paths. Use the full entries if you mirror the archives.

| Resource | SHA-256 |
| --- | --- |
| `europeana_schemas-20260720.zip` | `96093672357c46ee1f4644819fccb36f29395dffc78317c907dbe9895b74adbf` |
| `edm_sorter-20260630.xsl` | `421d1b942a06979f20ff338cb55944d86ab35f3bca6e711e20dcdf91ad4851a1` |
| `default_transformation.xslt` | `fa6e1ac795777b3c190c65088d752aa8eb721da778f69d86ee67f686f4016f1b` |

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

Check through WebHDP using an administrator access token stored in `TOKEN`.

```bash
WEBHDP_ORIGIN=https://hdp.example.org
curl -H "Authorization: Bearer $TOKEN" \
  "$WEBHDP_ORIGIN/api/v1/admin/edm-validator/status"
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
        "source_ref": "a7b3ad4",
        "image_tag": "local-edm-validator:local",
        "git_commit_short": "a7b3ad4",
        "build_time": "2026-11-25T10:00:00Z",
        "edm_schema_version": "20260720",
        "metis_schema_version": "15"
      }
    }
  }
}
```

## Operational Notes

- Keep `LOCAL_EDM_VALIDATOR_SOURCE_REF` aligned with the pinned validator commit before building the image.
- Record the image tag and source ref in release notes when validation behavior changes.
- If `LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true`, the validator returns all available step results instead of stopping at the first failure.
- Set `LOCAL_EDM_VALIDATOR_REQUIRED=true` for workflows that require the standalone validator. Both its external and internal validation stages must pass for the EDM attachment to be accepted.
- The July 2026 schema accepts the optional Europeana 3D advisory fields (`schema:digitalSourceType`, `edm:intendedUsage`, and 3D count properties). Set `EMIT_EUROPEANA_3D_ADVISORY_FIELDS=true` when you want WebHDP to emit them. WebHDP emits `edm:type` and `dc:type` for 3D regardless of this setting.
- Deployments that rely on WebHDP's built-in checks can set both `ENABLE_LOCAL_EDM_VALIDATION=false` and `LOCAL_EDM_VALIDATOR_REQUIRED=false`. Review the saved validation report to distinguish passed checks from skipped standalone stages.
- If the standalone validator is enabled, check reachability in **Settings → EDM Config**. Before rollout, generate a representative EDM attachment with the target WebHDP worker and confirm `VALIDATE_EXTERNAL` and `VALIDATE_INTERNAL` both pass. Check that an invalid fixture is rejected.

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
