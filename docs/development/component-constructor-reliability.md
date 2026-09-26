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

## Verification

- Backend suite: **621 passed, 1 skipped**.
- Frontend unit suite: **251 passed** across 71 files.
- Focused browser suite: **12 passed**, covering Chromium and Firefox, including constructor layouts at 375 and 1536 pixels and the installer at 375 pixels.
- Production frontend build and whitespace checks passed.
- Desktop and narrow-screen screenshots were inspected.

New regression cases cover stale responses, changed files and sources, interrupted preflight, rejected publication, cancelled discard, component import preserving edits, missing package sources, custom provenance, failed smoke tests, repeated version numbering and disabled dependencies. Existing suites continue to cover manifest schemas, bindings, triggers, output actions, installation and pipeline execution behavior.

Browser API responses are controlled fixtures. These results do not constitute a live HPC installation or rendering test. The pre-execution configuration comparison detects intervening saves but does not atomically pin execution against a concurrent publication after that comparison. Existing execution API semantics are retained.

Feature switches and deployment configuration are unchanged. No deployment, push or Zenodo publication is part of this change.
