# WebHDP Documentation Portal

Documentation scope: this public documentation describes the WebHDP alpha
repository and its supported local, Docker, and operator workflows. Re-run the
release checks and update the affected pages whenever setup, API, workflow, or
deployment behavior changes.

This documentation is organized by audience and task:
- Beginners: learn the WebHDP workflow and vocabulary
- Users: complete publication, credential, retrieval, and review workflows
- Operators: deploy, configure, monitor, and troubleshoot
- Developers: consume APIs and extend pipelines/templates

## Start Here

- [Workflow guide](guides/workflows.md)
- [Docker quickstart](guides/docker_quickstart.md)
- [Complete workflow inventory](workflows/README.md)
- [End-to-end workflow guide](guides/end_to_end_user_guide.md)
- [Glossary](guides/glossary.md)
- [Zenodo API key setup](guides/zenodo_api_keys.md)
- [Security and credentials](guides/security_and_credentials.md)
- [Zenodo account deep retrieval](guides/zenodo_account_retrieval.md)
- [Zenodo OAI harvest](guides/zenodo_oai_harvest.md)
- [Operations and setup guide](guides/operations_and_setup_guide.md)
- [Upgrade to v0.1.0-alpha.3](guides/upgrade_alpha3.md)
- [HPC local-mode setup](guides/hpc_local_mode_setup.md)
- [Run a live demo with a pre-reserved GPU](guides/prereserved_gpu_demo.md)
- [Troubleshooting guide](guides/troubleshooting.md)
- [Future roadmap and planned updates](guides/planned_future_updates.md)
- [Release walkthrough videos](guides/video_guides/release_walkthroughs.md)
- [Developer onboarding](development/onboarding.md)
- [Devcontainer setup](development/devcontainer.md)
- [First PR walkthrough](development/first_pr_walkthrough.md)
- [Developer troubleshooting decision tree](development/troubleshooting_decision_tree.md)
- [Contributor architecture map](development/architecture_map.md)
- [Developer glossary](development/developer_glossary.md)
- [PR size and scope examples](development/pr_scope_examples.md)
- [Known development warnings](development/known_warnings.md)
- [Contributor handbook](development/contributor_handbook.md)
- [Developer examples cookbook](development/examples.md)
- [Build your first HDP Component](development/first_hdp_component.md)
- [HMSM Studio components and pipelines](guides/hmsm_components.md)
- [Historic reconstruction components and pipelines](guides/historic_reconstruction.md)
- [Published Zenodo community components and pipelines](guides/zenodo_community_components.md)
- [Historic reconstruction source evaluation](development/historic_reconstruction_evaluation.md)
- [WebHDP-Link: application API, hosted processing and prototypes](guides/webhdp_link.md)
- [WebHDP-Link deployment runbook](guides/webhdp_link_deployment.md)
- [HDP Component manifest specification](development/hdp_component_manifest_specification.md)
- [HDP Component publishing guide](development/hdp_component_publishing_guide.md)
- [Good first changes](development/good_first_changes.md)
- [Golden sample workflow](development/golden_workflow.md)
- [Architecture decisions](development/adr/README.md)

## Documentation Map

| Area | Purpose | Primary Document |
|---|---|---|
| Start here | Beginner entry point, local setup, workflow overview, and shared vocabulary | [Docker Quickstart](guides/docker_quickstart.md), [End-to-End User Guide](guides/end_to_end_user_guide.md), [Glossary](guides/glossary.md) |
| Workflows | Task-focused guides and exhaustive workflow inventory for publication, MSF QA, credential setup, retrieval, import, record review, operations, API workflows, background jobs, native pipelines, and operator scripts | [WebHDP Workflow Guide](guides/workflows.md), [Complete Workflow Inventory](workflows/README.md), [End-to-End User Guide](guides/end_to_end_user_guide.md), [Zenodo Account Deep Retrieval](guides/zenodo_account_retrieval.md) |
| Account security | Zenodo keys, encrypted storage, sharing, password changes, and recovery codes | [Zenodo API Keys](guides/zenodo_api_keys.md), [Security and Credentials](guides/security_and_credentials.md) |
| Video guides | Accepted release recordings that show real, replayable workflows | [Release Walkthrough Videos](guides/video_guides/release_walkthroughs.md) |
| Operations | Setup, environment, modes, admin runbook, and HPC local-mode setup | [Operations and Setup Guide](guides/operations_and_setup_guide.md), [HPC Local-Mode Setup](guides/hpc_local_mode_setup.md), [Troubleshooting Guide](guides/troubleshooting.md) |
| Alpha upgrade | Database and worker upgrade, component pins, staging checks and restore | [Upgrade to v0.1.0-alpha.3](guides/upgrade_alpha3.md) |
| Pre-reserved GPUs | Share one operator-held Slurm GPU job with named users and rehearse the public site | [Pre-reserved GPU demo](guides/prereserved_gpu_demo.md) |
| Connected applications | Register an application, publish a pinned pipeline, and operate the Link worker | [WebHDP-Link integration](guides/webhdp_link.md), [WebHDP-Link deployment](guides/webhdp_link_deployment.md) |
| Reference | System boundaries, API contracts, schemas, and shared vocabulary | [System Architecture](architecture/system_architecture.md), [WebHDP API Reference](api/webhdp_api_reference.md), [HDPC Schema](architecture/hdpc_schema.md) |
| Developer onboarding | First-hour setup, contribution tracks, first-change guidance, and common pitfalls | [Developer Onboarding](development/onboarding.md) |
| Devcontainer setup | Ready VS Code/Codespaces environment for Python, Node, uv, Docker, and onboarding checks | [Devcontainer Setup](development/devcontainer.md) |
| First PR walkthrough | Developer first contribution path from workspace health check to focused first review | [First PR Walkthrough](development/first_pr_walkthrough.md) |
| Developer troubleshooting | Decision tree for doctor, frontend, API, auth, golden workflow, Docker, and Devcontainer failures | [Developer Troubleshooting Decision Tree](development/troubleshooting_decision_tree.md) |
| Contributor architecture map | Ownership map for frontend, Flask routes, services, models, tasks, `.hdpc`, and integrations | [Contributor Architecture Map](development/architecture_map.md) |
| Developer glossary | Implementation vocabulary for workflow, metadata, `.hdpc`, permissions, background work, Zenodo, and onboarding tools | [Developer Glossary](development/developer_glossary.md) |
| PR size and scope examples | Reviewable PR examples, split guidance, ADR triggers, and verification list patterns | [PR Size And Scope Examples](development/pr_scope_examples.md) |
| Known development warnings | Triage guide for known SQLAlchemy, Vitest, Browserslist, npm, uv, Docker, and Devcontainer warnings | [Known Development Warnings](development/known_warnings.md) |
| Developer contribution | Codebase map, layering rules, local setup, testing matrix, and review expectations | [Contributor Handbook](development/contributor_handbook.md) |
| Developer examples | Copyable implementation patterns for backend routes, services, migrations, Celery tasks, Vue views, tests, docs updates, and PRs | [Developer Examples Cookbook](development/examples.md) |
| First HDP Component | Step-by-step guide for turning an ordinary container into a manifest-backed HDP Component | [Build Your First HDP Component](development/first_hdp_component.md) |
| HDP Component manifest | Normative `component.yaml` field contract, runtime contract, UI metadata, validation rules, and best-practice checklist | [HDP Component Manifest Specification](development/hdp_component_manifest_specification.md) |
| HDP Component publishing | Detailed release, artifact, index, Git, Zenodo, trust, and verification workflow for sharing HDP Components | [HDP Component Publishing Guide](development/hdp_component_publishing_guide.md) |
| Good first changes | Scoped starter tasks and checks for new contributors | [Good First Changes](development/good_first_changes.md) |
| Golden sample workflow | Local fixture-backed scan, `.hdpc`, and MSF confidence check | [Golden Sample Workflow](development/golden_workflow.md) |
| Architecture decisions | Decision records explaining important WebHDP architecture constraints | [Architecture Decision Records](development/adr/README.md) |
| HDPC schema | Canonical `.hdpc` SQLite schema, migration rules, and export boundaries | [HDPC Schema](architecture/hdpc_schema.md) |
| API | Complete WebHDP endpoint reference | [WebHDP API Reference](api/webhdp_api_reference.md) |
| API usage | Practical request/response examples | [WebHDP API Examples](api/webhdp_api_examples.md) |
| API contract | Generated OpenAPI route inventory | [OpenAPI JSON](/api/v1/docs/assets/api/openapi.json) |
| Public embeds | Public record pages and oEmbed integration | [WebHDP API Reference](api/webhdp_api_reference.md), [Release Walkthrough Videos](guides/video_guides/release_walkthroughs.md) |
| Zenodo credentials | Named encrypted keys, live validation, sharing, active selection, and compatibility routes | [Zenodo API Keys](guides/zenodo_api_keys.md), [Security and Credentials](guides/security_and_credentials.md), [WebHDP API Reference](api/webhdp_api_reference.md) |
| Zenodo account retrieval | Retrieve published records and drafts from an accessible Zenodo key into persistent explorer-only `.hdpc` collections with incremental follow-up, search, export, scheduling, and compaction | [Zenodo Account Deep Retrieval](guides/zenodo_account_retrieval.md), [WebHDP API Reference](api/webhdp_api_reference.md) |
| Zenodo OAI harvest | Harvest public Zenodo OAI-PMH metadata without credentials for community monitoring, discovery, quality review, export, scheduling, and compaction | [Zenodo OAI Harvest](guides/zenodo_oai_harvest.md), [WebHDP API Reference](api/webhdp_api_reference.md) |
| Admin observability | Native credentials/integration status and API activity surfaces | [WebHDP API Reference](api/webhdp_api_reference.md) |
| Local EDM validator | Managed local-edm-validator deployment, status metadata, validation report persistence, and troubleshooting | [Local EDM Validator](guides/local_edm_validator.md) |
| Version detection | Batch record-resolution policy and global hash collision warnings | [Operations and Setup Guide](guides/operations_and_setup_guide.md), [WebHDP API Reference](api/webhdp_api_reference.md) |
| User workflow | What the workflow does and why each step exists | [End-to-End User Guide](guides/end_to_end_user_guide.md) |
| Future roadmap | Sustainability, architecture transition, interoperability, cloud transfer, embedded intelligence, multi-instance, human-in-the-loop, collections, and seeding plans | [Future Roadmap And Planned Updates](guides/planned_future_updates.md) |
| Troubleshooting | Failure modes and recovery actions | [Troubleshooting Guide](guides/troubleshooting.md) |

## Workflow Shortcuts

- [Workflow guide](guides/workflows.md): task map for publication, MSF QA, retrieval, credentials, import, operator, public-record, video walkthrough, and developer workflows
- [Complete Workflow Inventory](workflows/README.md): exhaustive coverage map for UI, API, background job, native pipeline, and operator-script workflows
- [Workflow Source Surface Coverage](workflows/source-surface-coverage.md): audit checklist mapping frontend routes, backend route families, Celery tasks, native pipelines, and scripts to workflow documents
- [End-to-End User Guide](guides/end_to_end_user_guide.md): the primary seven-step upload-to-submit workflow
- [Common Workflow Recipes](guides/common-workflow-recipes.md): single records, batch review, model derivatives, media-specific metadata, and recovery
- [Zenodo Account Deep Retrieval](guides/zenodo_account_retrieval.md): account-wide published/draft retrieval into explorer-only `.hdpc` shards
- [Zenodo OAI Harvest](guides/zenodo_oai_harvest.md): public OAI-PMH metadata harvesting into explorer-only `.hdpc` shards
- [Zenodo API Keys](guides/zenodo_api_keys.md): credential setup needed before publication or retrieval
- [Operations and Setup Guide](guides/operations_and_setup_guide.md): operator prerequisites and runbook checks
- [Docker Quickstart](guides/docker_quickstart.md): best-practice fresh-clone local Docker setup path
- [HPC Local-Mode Setup](guides/hpc_local_mode_setup.md): best-practice HPC setup without public server deployment or HPC-Link
- [Release Walkthrough Videos](guides/video_guides/release_walkthroughs.md): accepted real workflow recordings
- [Future Roadmap And Planned Updates](guides/planned_future_updates.md): forward-looking sustainability and roadmap backlog

## Related Documentation Paths

- Account and credential setup: [Zenodo API Keys](guides/zenodo_api_keys.md) and [Security and Credentials](guides/security_and_credentials.md)
- Retrieval workflows: [Zenodo Account Deep Retrieval](guides/zenodo_account_retrieval.md) and [Zenodo OAI Harvest](guides/zenodo_oai_harvest.md)
- API details: [WebHDP API Reference](api/webhdp_api_reference.md)

## Related Technical References

- [Storage Modes Architecture](storage_modes_architecture.md)
- [Docker Deployment Guide](docker_deployment_guide.md)
- [Docker Quickstart](guides/docker_quickstart.md)
- [HPC Local-Mode Setup](guides/hpc_local_mode_setup.md)
- [Local EDM Validator](guides/local_edm_validator.md)
- [Cloud Storage](cloud_storage.md)
- [Renderer Configuration](renderer_configuration.md)
- [HDPC Schema](architecture/hdpc_schema.md)
- [External Standards Links](standards_links.md)
- [Generated OpenAPI Contract](/api/v1/docs/assets/api/openapi.json)
- [System Architecture](architecture/system_architecture.md)
- [WebHDP API Examples](api/webhdp_api_examples.md)

Stabilized workflow note:
- Upload/scan documentation now reflects the shipped contract: upload ends at `scanned`, submit owns first-time record creation, reruns operate on `record_ids`, and LOD/credential behavior is explicit in the architecture and API docs.
- Zenodo credential documentation reflects the current named-key model: users can keep separate Sandbox and Production keys, accept shared access from other users, choose one active key per environment, and validate access through a live create/delete draft probe. Tokens are encrypted at rest and never returned as cleartext.
- Zenodo account retrieval documentation covers the Tools workflow for account-wide published/draft retrieval, rate-limited date-window harvesting beyond 10,000 account records, pause/resume behavior, incremental follow-up retrievals, collection search/export/scheduling/compaction, retrieval-generated `.hdpc` shards, and explorer-only session semantics.
- Zenodo OAI harvest documentation covers the public, no-credential OAI-PMH workflow for community metadata monitoring, including `user-3dbigdataspace` testing, DataCite/DCAT metadata options, incremental overlap, and explorer-only shard semantics.
- Zenodo account retrieval was live-verified on April 30, 2026 against a large production account: 83,657 records were retrieved into 848 explorer-only `.hdpc` shards, with adaptive dense-window splitting and checkpoint resume.

## Quality Principles Used In This Documentation

- Explain both mechanism and rationale (the "what" and the "why")
- Keep terminology explicit and consistent
- Separate user-facing workflows from operator runbooks
- Provide copy/paste API examples for integration
- Surface known constraints and degraded modes explicitly
