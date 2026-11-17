# Unpublished Zenodo Sandbox drafts

This operator-installed component creates an unpublished draft **only on
https://sandbox.zenodo.org**, uploads a source OBJ, converted GLB, geometry report,
prepared metadata and ZIP package, then downloads every file to verify its size
and SHA-256. It has no publication operation and cannot access production Zenodo.

Install the existing `link_mesh_packager` component, then call
`external_code.webhdp_link_zenodo.seed.seed(app.native_pipeline_service)` from an
application context. Register the returned publication payload with the Link
service and allowlist `link-model-sandbox-draft` for the intended application.
The two native pipeline steps use artifact bindings and pinned component versions.

The initiating user must select an accessible active **Sandbox** credential in
WebHDP. The existing `ZenodoCredentialService` stores it encrypted; no token is
included in the component manifest, pipeline, public parameter schema, receipt or
command line. The worker injects it in the approved component's environment only
after checking the exact component name, version, interpreter, runner and SHA-256.
The component uses Bearer authorization headers, fixed HTTPS endpoints, disabled
redirects and no environment proxies. It needs Sandbox deposition write/read
access. Its transport implements no `/actions/publish` request.

Only dataset title, description and one creator name are accepted. Draft metadata
uses restricted access; publication would require a separate operator workflow.
Files are limited to 100 MiB each and use simple safe filenames. The local mesh
preparation policy supports triangular geometry-only OBJ, without external files.

The private `sandbox-operation-state.json` checkpoint is fsynced before draft
creation and after each verified upload. A confirmed draft may be resumed only
with identical inputs; changed or unexpected files are never overwritten.
An interrupted creation without a confirmed identity stops for operator
reconciliation rather than creating a second draft. Job cancellation can leave an
unpublished remote draft; it does not delete it. The checkpoint is kept in the
private job workspace and is not exposed as a Link artifact. The success receipt
contains only the draft URL, safe metadata, file checksums and verification status.

Protocol reference: [Zenodo REST API](https://developers.zenodo.org/) and
[Zenodo upload documentation](https://help.zenodo.org/docs/deposit/create-new-upload/).
Sandbox drafts are testing records, not published scientific deposits.
