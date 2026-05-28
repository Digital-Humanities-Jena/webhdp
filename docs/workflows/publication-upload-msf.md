# Publication, Upload, And MSF Workflows

This document covers the primary publication path and the ingestion/MSF
workflows that prepare a session for processing.

## Overview

This is the main path from source files to a processable WebHDP session. It
covers upload, directory and ZIP ingestion, local preparation, streaming upload,
upload recovery, MSF parsing and repair, record-resolution review, and the final
handoff toward processing. Read the top workflow sections for the user journey;
use the bottom sections when optimizing throughput, recoverability, or gates.

## Use Cases

- Publish source files through the main upload-to-submit workflow.
- Diagnose file, directory, ZIP, streaming, local-mode, and cloud-assisted ingestion.
- Repair MSF parse, validation, metadata matching, and local export issues.
- Recover interrupted uploads and monitor submission progress.

## Main Publication Workflow

Primary actor: WebHDP publishing user.

Entry points:
- UI: `/workflow/upload`
- UI: `/workflow/msf-analysis`
- UI: `/workflow/files`
- UI: `/workflow/metadata`
- UI: `/workflow/edm-selection`
- UI: `/workflow/pipeline`
- UI: `/workflow/submit`
- UI: `/workflow/processing`
- UI: `/submissions`
- UI: `/submissions/:id`

Workflow:
1. Upload or scan source files.
2. Complete MSF QA when the session is MSF-driven batch mode.
3. Review discovered files and select the processing set.
4. Save submission metadata or confirm MSF-derived metadata.
5. Select EDM/LOD behavior and validate output.
6. Select a pipeline.
7. Submit the pipeline and monitor processing.
8. Review records, Zenodo links, and provenance.

Complete when:
- The submission reaches `completed`, or a failure is triaged from the submission detail page.

## Upload And Scan

Primary actor: publishing user.

Entry points:
- API: `/api/v1/sessions/file`
- API: `/api/v1/sessions/directory`
- API: `/api/v1/sessions/tasks/<task_id>`
- API: `/api/v1/sessions/<session_id>/progress`
- API: `/api/v1/submissions`
- API: `/api/v1/submissions/<submission_id>`
- API: `/api/v1/submissions/<submission_id>/progress`
- Celery: `start_upload_coordinator`
- Celery: `process_single_file_task`
- Celery: `finalize_session_upload`

Workflow:
1. Create a session from a single file, directory, or ZIP.
2. Stage files in the session workspace.
3. Scan and register source files into `.hdpc`.
4. Persist upload progress and task IDs.
5. Normalize the session state to `scanned` or `failed`.

Complete when:
- Session progress reports scan completion and file nodes are available.

## Local Workflow Preparation And Scan Start

Primary actor: administrator or local-mode publishing user.

Entry points:
- API: `/api/v1/msf/workflow/local/prepare`
- API: `/api/v1/msf/workflow/session/<session_id>/start-local-scan`
- API: `/api/v1/sessions/local-msf`

Workflow:
1. Select a local input directory and optional MSF file.
2. Prepare a workflow session without scanning immediately.
3. Run MSF analysis and repair first.
4. Start the real local scan when blockers are resolved.

Complete when:
- The prepared session has started and completed the local scan.

## Streaming Cloud Upload

Primary actor: publishing user or HPC-assisted client.

Entry points:
- API: `/api/v1/upload/stream`

Workflow:
1. Stream a file body with required filename and size headers.
2. Store the file through the configured cloud upload service.
3. If an HPC allocation ID is provided, stage the resulting cloud reference to HPC.

Complete when:
- The upload response includes the cloud object reference and any requested HPC staging result.

## Upload Recovery And Resume

Primary actor: user returning to an interrupted upload.

Entry points:
- API: `/api/v1/sessions/directory/recover`
- API: `/api/v1/sessions/<session_id>/resume`
- UI: `/uploads`
- UI: `/uploads/:sessionId`
- API: `/api/v1/sessions/upload-operations`
- API: `/api/v1/sessions/upload-operations/<session_id>`

Workflow:
1. Load persisted upload operation state.
2. Recover a directory submission when browser state was lost.
3. Resume a session from persisted workflow metadata.
4. Continue at the correct workflow step.

Complete when:
- The user can continue from the recovered session instead of restarting ingestion.

## MSF Parsing, Validation, Repair, And Metadata Matching

Primary actor: batch publishing user or operator.

Entry points:
- API: `/api/v1/msf/upload`
- API: `/api/v1/msf/parse`
- API: `/api/v1/msf/validate`
- API: `/api/v1/msf/detect-filename-column`
- API: `/api/v1/msf/default-mapping`
- API: `/api/v1/msf/metadata-for-files`
- API: `/api/v1/msf/patch`
- API: `/api/v1/msf/workflow/session/<session_id>/analyze`
- API: `/api/v1/msf/tools/local/context`
- API: `/api/v1/msf/tools/local/validate`
- API: `/api/v1/msf/tools/local/export`

Workflow:
1. Upload or select an MSF file.
2. Parse CSV/XLS/XLSX content with selected options.
3. Detect filename columns and metadata columns.
4. Validate file references, required fields, duplicates, whitespace, and repairable issues.
5. Generate metadata for selected files.
6. Apply guided patch operations and export repaired MSF output when needed.
7. Re-run workflow-session analysis before file review.

Complete when:
- Blocking MSF issues are resolved or accepted according to policy.
- Metadata can be matched to selected files.

## Record-Resolution Review

Primary actor: batch publishing user.

Entry points:
- API: `/api/v1/sessions/<session_id>/record-resolution`
- API: `/api/v1/sessions/<session_id>/record-resolution/analyze`

Workflow:
1. Analyze candidate records for duplicate, version, and global hash-collision signals.
2. Review accessible matching Zenodo records and hidden-match counts.
3. Choose actions such as create fresh record, create version, or skip.
4. Save the plan before continuing.

Complete when:
- Every required candidate has a saved action and the workflow can proceed.

## Prerequisites And Permissions

- Upload and publication workflows require an authenticated user with permission to create or edit the session.
- Zenodo publication requires a valid credential for the intended sandbox or production environment.
- Local workflow preparation and local MSF tools require local storage mode and, for tool access, administrator context where enforced.
- Streaming upload and HPC-assisted staging require configured cloud storage and optional HPC allocation context.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| File, directory, ZIP, cloud reference, or local path | Session workspace and `.hdpc` source records | upload operation, task ID, session status |
| MSF file and parse options | Parsed rows, validation report, metadata matches | MSF profile, repair plan, blocking errors |
| Workflow selections and metadata | Ready-to-submit session | workflow state, selected files, metadata draft |
| Record-resolution decisions | Saved duplicate/version/hash-collision plan | candidate actions, hidden matches, global hash warnings |
| Submission request | Processing submission and progress | submission status, pipeline task, generated records |

## Failure And Recovery

- Interrupted upload should resume from upload operation state or directory recovery when available.
- MSF blockers should be repaired, exported, or explicitly accepted before file review.
- Missing file references require checking storage mode, local paths, ZIP contents, or cloud object availability.
- Failed submission should be triaged from submission detail, pipeline progress, task state, and session records.

## Optimization Targets

- Reduce scan time for large directories and ZIP archives.
- Keep upload progress responsive without excessive polling.
- Make MSF parsing and metadata matching efficient for large spreadsheets.
- Minimize repeated `.hdpc` writes during ingestion and repair.
- Catch duplicate/version decisions before expensive processing starts.

## Verification Checklist

- Verify single-file, directory, ZIP, local-prepare, local-scan, and streaming upload paths.
- Verify upload operation list/detail, task polling, recovery, and resume behavior.
- Verify MSF upload, parse, validate, detect filename column, patch, local validate, and export.
- Verify record-resolution analyze/save behavior.
- Verify submit, processing progress, submission detail, and final record/provenance availability.

Related docs:
- `docs/guides/end_to_end_user_guide.md`
- `docs/guides/workflows.md`
- `docs/development/adr/0001-upload-scan-submit-lifecycle.md`

## Codebase Starting Points

- Workflow views: `frontend/src/views/workflow/UploadView.vue`, `frontend/src/views/workflow/MsfAnalysisView.vue`, `frontend/src/views/workflow/FilesView.vue`, `frontend/src/views/workflow/ProcessingView.vue`
- Submission and upload views: `frontend/src/views/dashboard/SubmissionsView.vue`, `frontend/src/views/dashboard/UploadOperationsView.vue`
- Session ingestion routes: `routes/session_routes.py`
- MSF routes and repair helpers: `routes/msf_routes.py`
- Streaming upload route: `routes/upload_routes.py`
- Submission routes: `routes/submission_routes.py`
- Upload and processing tasks: `tasks.py`
- Upload lifecycle ADR: `docs/development/adr/0001-upload-scan-submit-lifecycle.md`
