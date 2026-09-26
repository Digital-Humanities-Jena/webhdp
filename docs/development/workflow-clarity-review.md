# Workflow clarity review

Reviewed 2026-09-26 through the workflow views, onboarding, existing browser scenarios and responsive screenshots. This is an interface review, not a study with new users.

## Findings and implemented changes

| New-user question | Previous obstacle | Change |
| --- | --- | --- |
| Where do I start? | An empty dashboard had only a sentence; request failures also looked empty. | Explain sessions, link directly to upload, and separate loading, errors with retry, and an empty workspace. |
| Why did I skip a step? | Single-file uploads displayed the batch-only spreadsheet step and seven-step numbering. | Display six steps for a single file and seven for a batch. Persisted step identifiers remain unchanged so saved sessions still resume correctly. |
| What do I need to do here? | Several pages repeated only their step number or an abbreviation. | Give each stage a short task and outcome, with additional help collapsed by default. Explain MSF, bundles, EDM, linked open data, pipelines and HPC at the point of use. |
| How do I prepare several files? | The batch option assumed prior knowledge of MSF layout and model dependencies. | Use a plain batch label, show a ZIP with a model, material and texture, and provide an editable CSV starter. Explain unique filenames and one row per main model. |
| Do I need a compute allocation before uploading? | Resource controls preceded the choice of upload path. | Put file choice first and explain that resources are needed for rendering. Distinguish access approval from a ready allocation. |
| Is my account ready? | Any HPC request, including pending or rejected requests, counted as done. | Show awaiting approval, not approved, or access enabled according to the actual state. Explain when each setup item is needed. |
| Is this published? | Completion copy broadly implied successful submission to Zenodo. | Explain Sandbox versus Production, drafts versus processing completion, and send users directly to records and results after processing. |
| Can I choose a template without a mouse? | Template cards only handled clicks. | Use labelled native radio inputs with keyboard focus and selection semantics. |

## Scope

The changes affect guidance, presentation, navigation and recovery states. They do not change uploads, record creation, renderer execution, publication policy or the storage configuration. Help is available in place rather than in a mandatory tour. Detailed settings and examples remain expandable.

The CSV is a starting layout with synthetic data, not complete publication metadata. Users replace its filenames and descriptions and resolve required metadata during the guided workflow.

## Verification

Automated checks cover single-file and batch step numbering, unchanged persisted step identities, pending/rejected/approved HPC states, a downloadable CSV, dashboard failure and retry, upload transitions, keyboard interaction, and layouts at 320, 375, 768 and 1280 pixels. Browser API responses are controlled fixtures; these checks do not allocate HPC resources or create Zenodo records. Inspect the records and results screen after a real processing run during the next authorized deployment validation.

Validation results: 241 frontend unit tests passed; 27 focused Chromium/Firefox browser tests passed with one intentional browser-specific skip; the production frontend build passed. The wider browser run also exercised authentication, upload/resume, administration and record views; its failures were outdated wording and an ambiguous test alert selector, corrected and rerun in the focused suite. Desktop and mobile screenshots were inspected.

No deployment is part of this change.
