# HDP Components and Pipeline Constructor review

Reviewed 2026-09-26 through source inspection, regression tests and responsive browser screenshots. This is an engineering and interface review, not a user study.

## Findings and changes

| Problem | Implemented behavior |
| --- | --- |
| Validation could remain green after editing a definition or installation source. | Checks are invalidated synchronously when their inputs change. Late responses are discarded when they describe different inputs. Repeated checks clear the previous result before starting. |
| Running an edited definition actually executed its saved counterpart. | Run requires an unchanged saved definition and successful preflight for the current session and paths. The saved configuration is fetched again before execution to detect intervening edits. The interface explains the blocking condition. |
| Component import could discard unrelated pipeline edits. | Import refreshes the component catalog without reloading the editor, and invalidates prior pipeline checks. |
| Navigation or switching pipelines could silently discard work. | Unpublished edits have a visible status, definition export and discard confirmation. Browser unload warns about edits or an active operation. |
| Overlapping operations could produce misleading state. | Forms and conflicting actions are disabled during operations, with method guards and visible progress. Pipeline and catalog loads discard superseded responses. |
| A component without a packaged image could reuse another component's source. | Selecting a component sets its source explicitly, including an empty source. Filtering does not silently select a different package. Custom manifests do not inherit catalog provenance. |
| Failed smoke tests appeared as successful completion notifications. | Only an explicit passing result is reported as success. Installation must return installed status; uncertain installation outcomes clear readiness and refresh history. |
| An unavailable catalog looked like an empty catalog. | Loading, failure with retry, and empty results are separate states. Playground component/session failures also provide recovery actions. |
| Runtime readiness was implied by the availability of a Playground form. | Copy distinguishes a test form, registered installation, runtime readiness and a passing smoke test. |
| Detailed diagnostics dominated the installer. | Raw validation, installation and smoke-test payloads are collapsed. The main interface shows the sequence, progress, check messages and next action. |
| Constructor layout overflowed at some desktop widths. | The center column can shrink, fields have accessible names, and the diagnostics panel follows validation, preflight and execution order. A preflight action is available beside the sample-file controls. |
| Repeated saves requesting an existing version could collide with the next existing version. | Version selection advances until an unused number is found, keeping the stored row and configuration aligned. |
| Enabled steps could depend on disabled producers or classifiers. | Server validation rejects these dependencies with instructions to enable the source or choose another one. |

## Reliability priorities completed

| Priority | Implemented behavior |
| --- | --- |
| Pin queued work to the checked definition. | Runs retain their pipeline version and persisted component versions. Saved definitions include component manifest hashes and pinned schemas. A signed, expiring preflight token binds the definition, user, session and selected paths. A later publication cannot change queued work. |
| Pin container artifacts. | Docker installations retain their immutable image ID. Publication rejects mutable Docker tags and SIF profiles without checksums. HPC-Link records SIF checksums and component versions; local and remote SIF runners reject modified images before execution. Existing remote component version directories cannot be overwritten. Built-in Python handlers remain part of the application deployment. |
| Report smoke tests honestly. | Missing test metadata returns `status: skipped`, `success: null`, and a separate readiness result. The interface never presents a skipped workload as a passing smoke test. |
| Keep long runs recoverable. | Constructor execution is asynchronous. The server stores progress, results, step failures and artifacts. User-scoped browser recovery and run links reconnect without resubmitting. Progress uses reported completed-file counts; unknown durations remain indeterminate. |
| Make retries and concurrent operations safe. | UUID request identities deduplicate runs, publications and installations. Publication identities survive restarts in the database. Cross-process registry locks protect version creation and installation; queued runs wait for session locks. Completed deliveries return stored results without rerunning processing. |
| Recover uncertain installations. | Lost responses retain the original request identity. Recovery checks the remote registry, matching both request identity and manifest before registering the installed artifact. Unconfirmed outcomes stay visibly unresolved and cannot silently start duplicate installations. An incomplete remote version directory requires operator inspection and a new version rather than overwriting artifacts. |
| Guide editing and repair. | Step cards collapse, show version/runtime/scope, and provide keyboard-accessible tabs. Removal identifies dependent steps and requests confirmation; removal and moves support Undo. Missing, disabled and out-of-order dependencies appear immediately with links to the affected connection. |
| Make sample selection understandable. | The session selector shows uploaded filenames, dates and file counts. The session file picker is primary; manual absolute paths are advanced controls. Runtime, scope and trigger labels use clearer terms. |
| Isolate optional diagnostics. | Catalog content renders independently of diagnostics, including when diagnostics are slow or unavailable. Errors are shown separately without hiding usable packages. Selection controls and external reference links are separate interactive elements. |

## Verification

- Backend suite: **632 passed, 1 skipped**.
- Frontend unit suite: **260 passed** across 72 files.
- HPC-Link suite: **113 passed, 1 skipped**, with 3 passing subtests.
- Focused browser suite: **14 passed** across Chromium and Firefox, including constructor layouts at 375 and 1536 pixels, the installer at 375 pixels, and run recovery after a page reload.
- Production frontend build and whitespace checks passed.
- The complete migration chain ran against a fresh SQLite database. The publication-request migration was also downgraded and upgraded again; both foreign keys were verified.
- Desktop and narrow-screen screenshots were inspected.
- Live validation on a Draco `vis` GPU allocation rendered OBJ, GLB and PLY fixtures, including a filename with spaces and Unicode. Each input produced two thumbnails. The existing SIF validator succeeded, and a deliberately incorrect checksum was rejected before execution.

Regression tests include concurrent process locks, queued version pinning, changed manifests and artifacts, repeated request identities, publication retries after a newer version, session authorization, interrupted submissions, installation reconciliation, delayed progress callbacks, skipped smoke tests, unavailable diagnostics, dependency repair and keyboard controls.

Browser responses use controlled API fixtures. The live GPU check exercised the staged component runner and real rendering/SIF workloads; it did not exercise a newly deployed WebHDP-to-HPC-Link HTTP integration. The opt-in live installation acceptance test remains skipped when its adapter and SIF settings are absent. These distinctions are intentional: readiness, unit/browser verification and live workload execution are reported separately.

## Deployment prerequisites

Apply database migration `c8d9e0f12345` with the normal application migration procedure. Upgrade HPC-Link and its component runner together with WebHDP when deployment is authorized; remote installation recovery uses the component-status endpoint and persisted request identity. Importing a manifest with a mutable image is still possible, but publishing an enabled container step requires installation or an explicit immutable digest/checksum. Existing unverified optional components remain subject to the configured feature switches.

Feature switches and deployment configuration are unchanged. No deployment, push, release-tag movement or Zenodo publication is part of this change.
