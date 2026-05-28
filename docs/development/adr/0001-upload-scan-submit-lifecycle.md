# ADR 0001: Upload, Scan, And Submit Lifecycle

Status: Accepted

## Context

WebHDP ingests heterogeneous heritage-science files, optional MSF spreadsheets, local processing outputs, and Zenodo publishing state. Earlier workflow designs can blur upload-time file registration with submit-time record creation, which makes reruns, provenance, and batch operations difficult to reason about.

## Decision

Upload and directory ingestion create a session, scan/register files, analyze MSF inputs, and stop at a resumable `scanned` state. Upload does not create Zenodo records.

Submit owns first-time local record creation from the selected files and final metadata. Reruns, batch operations, publish/discard/upload operations, and versioning operate on persisted `record_id` values.

## Consequences

- Contributors must not create canonical records during upload/scan code paths.
- UI resume behavior can rely on the `queued -> scanned -> submitting -> completed|failed` state model.
- Batch and post-submit operations can target stable record identifiers instead of re-inferring file selections.
- Changes to this lifecycle must update `docs/architecture/system_architecture.md`, API docs, frontend workflow state tests, and relevant task tests.
