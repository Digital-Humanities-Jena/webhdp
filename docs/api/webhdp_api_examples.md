# WebHDP API Examples

These examples use `curl` and assume:
- Base URL v1: `http://localhost:5000/api/v1`
- Base URL v2: `http://localhost:5000/api/v2`
- Public frontend URL: `http://localhost:8080`
- JWT token stored in `TOKEN`

```bash
export BASE_URL="http://localhost:5000/api/v1"
export BASE_URL_V2="http://localhost:5000/api/v2"
export PUBLIC_URL="http://localhost:8080"
export TOKEN="<jwt_token>"
```

## 1. Authenticate and Manage Zenodo Keys

### Login
```bash
curl -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"researcher@example.org","password":"<your_password>"}'
```

### Create a named personal sandbox key
```bash
curl -X POST "$BASE_URL/auth/me/zenodo-credentials" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "environment": "sandbox",
    "name": "Research sandbox key",
    "token": "<zenodo_sandbox_token>"
  }'
```

The response contains a credential ID and masked preview only. WebHDP stores the token encrypted and does not return it as cleartext.

### List available owned and shared keys
```bash
curl -X GET "$BASE_URL/auth/me/zenodo-credentials" \
  -H "Authorization: Bearer $TOKEN"
```

### Validate a named key
```bash
curl -X POST "$BASE_URL/auth/me/zenodo-credentials/<credential_id>/validate" \
  -H "Authorization: Bearer $TOKEN"
```

Validation uses live write cleanup mode: WebHDP lists depositions, creates a temporary draft, and deletes that draft.

### Set the active sandbox key
```bash
curl -X PUT "$BASE_URL/auth/me/zenodo-active-credentials/sandbox" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"credential_id": <credential_id>}'
```

### Share an owned key with another user
```bash
curl -X POST "$BASE_URL/auth/me/zenodo-credentials/<credential_id>/share" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"recipient_email": "collaborator@example.org"}'
```

The recipient must accept the share before the key can be used. Sharing grants access to the encrypted credential record; it does not disclose the cleartext token.

### Accept an incoming key share
```bash
curl -X POST "$BASE_URL/auth/me/zenodo-credential-shares/<share_id>/accept" \
  -H "Authorization: Bearer $TOKEN"
```

### Legacy environment-scoped compatibility validation
```bash
curl -X POST "$BASE_URL/auth/me/zenodo-credentials/sandbox/validate" \
  -H "Authorization: Bearer $TOKEN"
```

### Inspect Zenodo account retrieval context
```bash
curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/context" \
  -H "Authorization: Bearer $TOKEN"
```

The context response lists accessible named Zenodo keys, default scope, the page size, and the conservative request budget used by account retrieval.

### Start a bounded Zenodo account retrieval
```bash
curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "credential_id": <credential_id>,
    "max_records": 11000
  }'
```

Leave `max_records` out to retrieve every accessible record. Optional `start_datetime` and `end_datetime` values restrict the Zenodo `created` window for testing or targeted inventories.

### Start an incremental Zenodo account retrieval
```bash
curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "credential_id": <credential_id>,
    "sync_mode": "incremental",
    "incremental_overlap_hours": 24
  }'
```

Incremental mode uses the latest successful collection for the same credential and environment, subtracts the overlap from that collection's latest retrieved record timestamp, and queues only the follow-up window. Add `parent_retrieval_id` when a specific completed collection should be used.

### Poll retrieval progress
```bash
curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>" \
  -H "Authorization: Bearer $TOKEN"
```

Completed jobs include a manifest with generated shard sessions. Each shard is a persistent explorer-only session whose `.hdpc` records are marked as `zenodo_retrieval`.

### Search a retrieval collection
```bash
curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/records?q=amphora&limit=25" \
  -H "Authorization: Bearer $TOKEN"
```

The records endpoint searches across generated shard sessions. Optional filters include `status`, `capability`, `limit`, and `offset`.

### Export a retrieval collection
```bash
curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/manifest" \
  -H "Authorization: Bearer $TOKEN"

curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o zenodo-retrieval.csv

curl -X GET "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/archive" \
  -H "Authorization: Bearer $TOKEN" \
  -o zenodo-retrieval.zip
```

### Compact retrieval shards and update retention
```bash
curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/compact" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_records_per_shard": 5000}'

curl -X PATCH "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/retention" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "keep_original_shards": true,
    "keep_compacted_shards": true,
    "notes": "Keep originals until compacted archive is reviewed."
  }'
```

Compaction creates an additional compacted shard set. It is useful when a large retrieval produced many small shards, but the original retrieval shards remain the clearest audit trail.

### Schedule incremental follow-up retrievals
```bash
curl -X PATCH "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "frequency": "weekly",
    "incremental_overlap_hours": 24,
    "max_records": 5000
  }'

curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule/run-now" \
  -H "Authorization: Bearer $TOKEN"
```

The schedule endpoints are available only for completed collections. Browser clients need CORS preflight support for `PATCH` when the frontend and backend run on different origins.

### Pause, resume, or cancel a retrieval
```bash
curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/pause" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/resume" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>/cancel" \
  -H "Authorization: Bearer $TOKEN"
```

Pause and cancel are cooperative. Resume requeues the same retrieval ID and continues from the saved checkpoint.

If a worker or network interruption leaves a job visibly in `PROGRESS` but no retrieval process is alive, call the same resume endpoint. The resumed job continues from the persisted checkpoint and preserves already generated shard sessions.

### Delete generated retrieval shards
```bash
curl -X DELETE "$BASE_URL/tools/zenodo-account-retrieval/jobs/<retrieval_id>" \
  -H "Authorization: Bearer $TOKEN"
```

Deletion removes the generated shard sessions/files and the persisted retrieval history entry.

## 2. Start Directory Ingestion and Recover by Submit Token

### Start ingestion
```bash
curl -X POST "$BASE_URL/sessions/directory" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Upload-Submit-Token: demo-submit-token-001" \
  -F "zip_file=@/path/to/models.zip" \
  -F "msf_file=@/path/to/MSF.xlsx"
```

### Recover the upload context later
```bash
curl -X POST "$BASE_URL/sessions/directory/recover" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"submit_token":"demo-submit-token-001"}'
```

### Poll ingestion task
```bash
curl -X GET "$BASE_URL/sessions/tasks/<task_id>" \
  -H "Authorization: Bearer $TOKEN"
```

Operational note:
- Upload completion means the session has been scanned and is ready for workflow review.
- Upload does not create Zenodo records.

## 3. Inspect Session HDPC State

### Project summary
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/project-summary" \
  -H "Authorization: Bearer $TOKEN"
```

### Workspace summary
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/workspace-summary?is_sandbox=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Session workspace governance and publishing context
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/workspace" \
  -H "Authorization: Bearer $TOKEN"
```

### Paginated source files
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/files?page=1&limit=25&search=model" \
  -H "Authorization: Bearer $TOKEN"
```

### Full file tree
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/nodes" \
  -H "Authorization: Bearer $TOKEN"
```

## 4. Query Record Traceability and Zenodo Read Models

### Session records
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/records" \
  -H "Authorization: Bearer $TOKEN"
```

Operational note:
- Before first submit, this list can be empty even when upload/scan is complete.
- After submit, this endpoint returns canonical submit-flow records and hides legacy placeholder rows.

### Record lineage
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/records/<local_record_id>/lineage" \
  -H "Authorization: Bearer $TOKEN"
```

### Record traceability
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/records/<local_record_id>/traceability" \
  -H "Authorization: Bearer $TOKEN"
```

### Uploadable Zenodo items
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/zenodo/uploadable-files?is_sandbox_for_drafts=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Uploads grouped by product tab
```bash
curl -X GET "$BASE_URL/sessions/<session_id>/zenodo/uploads-by-tab?tab_id=published&is_sandbox=true" \
  -H "Authorization: Bearer $TOKEN"
```

## 5. Match Files and Create a New Zenodo Version

### Match a local directory against published concepts
```bash
curl -X POST "$BASE_URL/sessions/<session_id>/versioning/match-files" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "directory_path":"/data/local_input/version-candidate",
    "match_method":"filename"
  }'
```

### Create a new version for a local record
```bash
curl -X POST "$BASE_URL/sessions/<session_id>/records/<local_record_id>/create-version" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "absolute_file_paths":[
      "/data/local_input/version-candidate/model.glb",
      "/data/local_input/version-candidate/preview.png"
    ],
    "publish": false
  }'
```

### Discard a draft version
```bash
curl -X POST "$BASE_URL/sessions/<session_id>/records/<local_record_id>/discard-draft" \
  -H "Authorization: Bearer $TOKEN"
```

## 6. Import and Share HDPC Files

### Import an existing `.hdpc`
```bash
curl -X POST "$BASE_URL/sessions/import-hdpc" \
  -H "Authorization: Bearer $TOKEN" \
  -F "hdpc_file=@/path/to/session.hdpc"
```

### Download raw session `.hdpc`
```bash
curl -L "$BASE_URL/sessions/<session_id>/hdpc" \
  -H "Authorization: Bearer $TOKEN" \
  -o session_<session_id>.hdpc
```

### Download sanitized shared export
```bash
curl -L "$BASE_URL/sessions/<session_id>/hdpc/shared" \
  -H "Authorization: Bearer $TOKEN" \
  -o session_<session_id>_shared.hdpc
```

## 7. Dataset Duplicate Review

### Summarize duplicate groups for a dataset
```bash
curl -X GET "$BASE_URL/datasets/my-dataset/duplicates?environment=production" \
  -H "Authorization: Bearer $TOKEN"
```

### Run duplicate detection for prepared session files
```bash
curl -X POST "$BASE_URL/datasets/duplicate-check" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 42,
    "environment": "production"
  }'
```

### Analyze batch record resolution with global hash collision warnings
```bash
curl -X POST "$BASE_URL/sessions/42/record-resolution/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "policy_override": "balanced"
  }'
```

The response may include `warning` candidates with `reason_codes` containing `global_hash_collision`. Matching Zenodo records are returned in `matched_records` and include `record_link` when a public Zenodo URL can be built.

### Save record-resolution decisions after warning review
```bash
curl -X PUT "$BASE_URL/sessions/42/record-resolution" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "policy_override": "balanced",
    "decisions": [
      {
        "decision_key": "dataset-a::models/object.glb",
        "action": "create_fresh_record",
        "resolved": true
      }
    ]
  }'
```

### Update the default global hash collision policy
```bash
curl -X POST "$BASE_URL/admin/version-detection-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "balanced",
    "allow_force_create_fresh": true,
    "enabled_signals": {
      "hash_matching": true,
      "metadata_similarity": true
    },
    "hash_collision_policy": {
      "enabled": true,
      "min_size_bytes": 1048576,
      "excluded_extensions": [".csv", ".json", ".log", ".md", ".text", ".tsv", ".txt", ".xml"],
      "exclude_generated_renders": true
    }
  }'
```

## 8. Institution Credential Management

### Save institution production credential
```bash
curl -X PUT "$BASE_URL/institutions/<institution_id>/zenodo-credentials/production" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token":"<institution_production_token>"}'
```

### Validate institution production credential
```bash
curl -X POST "$BASE_URL/institutions/<institution_id>/zenodo-credentials/production/validate" \
  -H "Authorization: Bearer $TOKEN"
```

Institution tokens are also encrypted at rest and returned only as masked previews. Validation uses the same live read, temporary draft create, and cleanup probe used for personal keys.

## 9. Execute First Submit and Record-Based Rerun

### Check selected sources before execution

```bash
curl -X POST "$BASE_URL_V2/pipelines/<pipeline_id>/readiness" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 42,
    "local_file_paths": ["/data/session/uploads/model_a.glb"],
    "is_sandbox": true,
    "abort_on_critical_error": false
  }'
```

Inspect `data.ready`, `data.blockers`, and `data.unverified`. When ready, pass
`data.readiness_token` as `readiness_token` and `data.pipeline_version` as
`expected_version` with the same selection and settings to execution. The check
has no remote effects; runtime and generated-output checks remain deferred.
Repeat the check after edits or after one hour before starting a new request.

### First submit on selected files
```bash
curl -X POST "$BASE_URL_V2/pipelines/<pipeline_id>/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 42,
    "local_file_paths": [
      "/data/session/uploads/model_a.glb",
      "/data/session/uploads/model_b.glb"
    ]
  }'
```

### Rerun on existing records
```bash
curl -X POST "$BASE_URL_V2/pipelines/<pipeline_id>/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 42,
    "record_ids": [101, 102]
  }'
```

Operational note:
- Use `local_file_paths` for the first submit.
- Use `record_ids` for reruns and post-submit execution paths.

## 10. Local Admin Tooling

### Pipeline preflight in local mode
```bash
curl -X POST "$BASE_URL/tools/pipeline-preflight/local" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "msf_path":"collections/demo.xlsx",
    "directory_path":"collections/demo",
    "recursive": true
  }'
```

### Local EDM/IIIF/METS preview
```bash
curl -X POST "$BASE_URL/tools/output-preview/local" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "msf_path":"collections/demo.xlsx",
    "directory_path":"collections/demo",
    "targets":["edm","iiif","mets"]
  }'
```

## 11. HDP Component Installation

These endpoints require an admin token. Use `local_container` only on a
workstation-local deployment with safe Docker access from the backend/worker
process.

### List local Docker installable components
```bash
curl -G "$BASE_URL/tools/hdp-components/catalog" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "install_strategy=local_container"
```

### List configured remote-index components
```bash
curl -G "$BASE_URL/tools/hdp-components/catalog" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "install_strategy=local_container" \
  --data-urlencode "source=remote"
```

Remote indexes are disabled unless `WEBHDP_COMPONENT_INDEX_SOURCES` is set to
one or more HTTPS URLs or absolute local JSON paths using schema
`webhdp.component-index.v1`. While the repository is unpublished, use the local
fixture at `docs/examples/component-index/index.json` with an absolute path.

### Inspect component index diagnostics
```bash
curl -G "$BASE_URL/tools/hdp-components/catalog/diagnostics" \
  -H "Authorization: Bearer $TOKEN"
```

The response includes configured source count, cache state, current WebHDP
version, timeout/TTL settings, and the active minimum trust level.

### Validate a local Docker component package
```bash
curl -X POST "$BASE_URL/tools/hdp-components/validate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "install_strategy": "local_container",
    "manifest_text": "metadata:\n  name: gltf_validator\n  version: \"1.0.0\"\n...",
    "container_image": "webhdp-gltf-validator:local",
    "catalog_ref": {
      "source": "https://example.org/webhdp-components/index.json",
      "component_key": "gltf_validator",
      "version": "1.0.0",
      "manifest_url": "https://example.org/webhdp-components/gltf_validator/component.yaml"
    },
    "trust_level": "community-reviewed",
    "release": {
      "url": "https://codeberg.org/example/gltf-validator/releases/tag/v1.0.0",
      "tag": "v1.0.0"
    },
    "docker_digest": "sha256:..."
  }'
```

Validation checks manifest shape, Docker image availability, and image policy
such as `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST`.

### Install and smoke-test the local Docker component
```bash
curl -X POST "$BASE_URL/tools/hdp-components/install" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "install_strategy": "local_container",
    "manifest_text": "metadata:\n  name: gltf_validator\n  version: \"1.0.0\"\n...",
    "container_image": "webhdp-gltf-validator:local"
  }'

curl -X POST "$BASE_URL/tools/hdp-components/installations/<installation_id>/test" \
  -H "Authorization: Bearer $TOKEN"
```

Local smoke tests use the manifest `install.test` fixture, run the container
with `--network none`, and require a successful WebHDP component response.

### Validate and install an HPC SIF component
```bash
curl -X POST "$BASE_URL/tools/hdp-components/validate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "install_strategy": "hpc_sif",
    "manifest_text": "metadata:\n  name: gltf_validator\n  version: \"1.0.0\"\n...",
    "sif_source": "/work/components/gltf_validator.sif",
    "sif_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }'

curl -X POST "$BASE_URL/tools/hdp-components/install" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "install_strategy": "hpc_sif",
    "manifest_text": "metadata:\n  name: gltf_validator\n  version: \"1.0.0\"\n...",
    "sif_source": "/work/components/gltf_validator.sif",
    "sif_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }'
```

HPC smoke tests use `hpc.test` and run through HPC-Link. Do not run live Draco
acceptance tests while production jobs are active.

## 12. Admin Observability

### Local EDM validator status
```bash
curl -X GET "$BASE_URL/admin/edm-validator/status" \
  -H "Authorization: Bearer $TOKEN"
```

The response includes enabled state, configured endpoint, `/actuator/health` reachability, and `/actuator/info` version/source metadata. This is the API equivalent of Settings -> EDM Config.

### Credential and integration status
```bash
curl -X GET "$BASE_URL/admin/observability/credentials-status" \
  -H "Authorization: Bearer $TOKEN"
```

### API activity feed
```bash
curl -X GET "$BASE_URL/admin/observability/api-activity?integration=zenodo&page=1&per_page=20" \
  -H "Authorization: Bearer $TOKEN"
```

## 13. Public Record oEmbed

These endpoints are unauthenticated and only resolve published public Zenodo records.

### Public record payload
```bash
curl -X GET "$BASE_URL/public/records/zenodo/<zenodo_record_id>"
```

Use `sandbox` instead of `zenodo` for sandbox records:
```bash
curl -X GET "$BASE_URL/public/records/sandbox/<zenodo_record_id>"
```

### oEmbed JSON profile
```bash
curl -G "$BASE_URL/oembed" \
  --data-urlencode "url=$PUBLIC_URL/p/records/zenodo/<zenodo_record_id>" \
  --data-urlencode "format=json" \
  --data-urlencode "maxwidth=640" \
  --data-urlencode "maxheight=480"
```

The response is a raw oEmbed object, not the standard WebHDP success envelope:
```json
{
  "version": "1.0",
  "type": "rich",
  "title": "Public 3D Model",
  "provider_name": "WebHDP",
  "html": "<iframe src=\"https://webhdp.example.org/embed/records/zenodo/12345\" width=\"640\" height=\"480\" title=\"Public 3D Model\" loading=\"lazy\" allowfullscreen style=\"border:0;max-width:100%;aspect-ratio:640/480;\"></iframe>",
  "width": 640,
  "height": 480
}
```

### Browser routes
- Public landing page: `$PUBLIC_URL/p/records/zenodo/<zenodo_record_id>`
- Iframe embed page: `$PUBLIC_URL/embed/records/zenodo/<zenodo_record_id>`

## 14. Developer Diagnostics

Requires an admin, moderator, or user with `developer_access`.

```bash
curl -X GET "$BASE_URL/developer/status" \
  -H "Authorization: Bearer $TOKEN"
```

The response contains non-secret onboarding diagnostics:

```json
{
  "success": true,
  "data": {
    "developer_mode": true,
    "runtime": {
      "flask_env": "development",
      "storage_mode": "local",
      "inline_tasks_requested": true
    },
    "api_contract": {
      "path": "docs/api/openapi.json",
      "exists": true,
      "regenerate_command": "make api-contract"
    }
  }
}
```

## 15. Error Handling Pattern

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "match_method must be either 'filename' or 'hashcode'",
    "details": {}
  }
}
```

Related references:
- Full endpoint inventory: `webhdp_api_reference.md`
- Generated OpenAPI route inventory: `openapi.json`
- `.hdpc` schema and migration contract: `../architecture/hdpc_schema.md`
