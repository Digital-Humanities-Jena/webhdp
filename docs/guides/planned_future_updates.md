# Future Roadmap And Planned Updates

This document lists planned WebHDP directions after `v0.1.0-alpha.1` and
consolidates earlier roadmap notes into one public planning page. It is not a
release commitment. Items here should become concrete issues, milestones,
architecture decisions, or implementation specifications before they are treated
as scheduled work.

For the current alpha boundary, see `README.md` and `RELEASE_NOTES.md`.

This page is intentionally separate from current-release user documentation. It
collects future sustainability, governance, interoperability, and workflow
directions so the public alpha can be published without implying that these
items are already implemented.

## Planning Principles

- Keep the stable alpha paths (`render` and `metadata_only`) reliable while
  broadening component-driven and institution-scale workflows.
- Prefer open, versioned contracts over deployment-specific assumptions.
- Preserve human review points for publication, rights, metadata quality,
  community decisions, and compute-heavy operations.
- Treat HPC, cloud transfer, LLM assistance, and alternative endpoints as
  configurable capabilities with explicit operator policy.
- Separate public roadmap entries from private deployment details, credentials,
  and project-internal operational notes.

## Current Architecture Transition

Current alpha baseline:
- WebHDP production workflows still include predefined/default pipeline paths,
  especially `render` and `metadata_only`.
- Native component import, the HDP Component Playground, and the Pipeline
  Constructor already provide the foundation for component-driven workflows.
- Standalone HDP-Server deployment is not part of the standard alpha
  operational baseline.
- Repository release preparation does not include deployment, synchronization,
  or remote execution on HPC.

Planned direction:
- Move production workflow composition toward manifest-backed HDP Components.
- Keep current stable paths available until component-driven equivalents are
  proven through tests, operator documentation, and migration guidance.
- Treat HPC execution as an explicit operator capability rather than an assumed
  dependency of a public repository clone.

## WebHDP And HDP Server Alignment

The earlier WebHDP + HDP Server direction is folded into this roadmap. The
working-paper alignment remains useful as architecture context, but public
release documentation should point users to implemented WebHDP behavior first.

### HPC Resources, Components, And Playground

Implemented foundation:
- HDP Components can be installed with local-container or HPC/SIF strategies.
- Local Docker smoke tests use component test contracts.
- The Playground can test single components before full pipeline runs.

Planned outcome:
- Link permissioned HPC allocations directly with more production pipeline
  steps where a deployment enables that capability.
- Broaden operational guidance for quotas, scheduling, long-running remote
  jobs, cancellation, and recovery.

Open work:
- Define allocation visibility and permission checks.
- Provide clear queued/running/failed/completed lifecycle states.
- Keep a tested fallback path for deployments without HPC availability.

### Record Preview And Draft Management

Planned outcome:
- Add explicit record preview and draft-management surfaces before final
  publication actions.

Open work:
- Separate prepared, draft, submitted, and published states in the UI.
- Improve handoff from user submission to moderator or administrator review.
- Add conflict handling when drafts are updated concurrently.

### Enhanced LOD And EDM Validation

Planned outcome:
- Expand structural, semantic, and relational validation for LOD outputs.
- Keep local EDM validation fast and visible through persisted reports.

Open work:
- Maintain validator rule sets as standards evolve.
- Add clearer remediation hints for failed checks.
- Balance strictness with usability for non-technical users.

### Institutional Accounts, Groups, And Communities

Planned outcome:
- Extend the current user and institution model toward governed multi-user
  publication and moderation workflows.

Open work:
- Define group-scoped visibility and collaboration controls.
- Improve migration paths for individual accounts moving into institutional
  contexts.
- Add auditable review and approval flows.

### Cloud Transaction Mirroring

Planned outcome:
- Mirror key transaction artifacts into organization-controlled cloud storage
  for auditability and recovery.

Open work:
- Define retention policy, replay behavior, and consistency guarantees.
- Keep storage cost and failure states visible to operators.

## Sustainability And Governance

### ECCCH-INFINITY Technical Rulebook Alignment

Planned outcome:
- Review WebHDP against the ECCCH-INFINITY Technical Rulebook v1 when the
  project rulebook is available to the WebHDP maintainers.
- Convert rulebook requirements into traceable compliance checks, architecture
  decisions, and operator documentation.

Open work:
- Identify mandatory versus recommended rulebook requirements.
- Add a compliance matrix that maps requirements to code, configuration,
  documentation, tests, and deployment evidence.
- Record gaps as release-blocking or non-blocking depending on the target
  publication or deployment context.

### Development Roadmap

Planned outcome:
- Maintain a public roadmap that distinguishes research prototypes, evaluated
  alpha features, committed release work, and long-term research directions.

Open work:
- Convert this document into issue/milestone groups after repository
  publication.
- Add status markers such as `idea`, `research`, `design`, `prototype`,
  `alpha`, `beta`, and `release-ready`.
- Keep roadmap entries version-bound so older documentation remains historically
  understandable.

## Data Movement And Storage

### Cloud Transfer Instead Of Browser Upload

Planned outcome:
- Let users provide a supported cloud storage link or object reference instead
  of uploading all source data through the browser.

Open work:
- Define the accepted link/reference formats for supported providers.
- Validate access, size, file count, checksums, and directory structure before
  creating a session.
- Preserve provenance so transferred files are distinguishable from browser
  uploads and local/HPC scans.
- Provide user-facing failure states for expired links, missing permissions,
  unsupported providers, and partial transfers.

### Connecting Multiple WebHDP Instances

Planned outcome:
- Support controlled transfer of state between local, HPC-hosted, and
  web-deployed WebHDP instances.

Candidate flows:
- local workstation to institutional web instance
- HPC processing instance to web publication instance
- personal research instance to institution-managed instance

Open work:
- Define export/import contracts for sessions, `.hdpc` files, records,
  accounts, institutions, credentials metadata, and audit history.
- Never transfer cleartext credentials. Use invitation, re-authentication, or
  recipient-side credential binding.
- Decide how conflicts are handled when the same record, session, user, or
  institution exists on multiple instances.
- Add integrity checks and migration reports before accepting imported state.

## Publication Endpoints And Interoperability

### Endpoint Variability

Planned outcome:
- Open WebHDP beyond a Zenodo-only publication model while keeping Zenodo as the
  first supported repository endpoint.

Candidate endpoints:
- Zenodo and Zenodo Sandbox
- ECCCH-aligned repositories or aggregators
- institutional repositories
- provider-specific APIs for project deployments

Open work:
- Define a publication endpoint interface for authentication, draft creation,
  file upload, metadata mapping, publication, versioning, deletion, and status
  checks.
- Separate endpoint-neutral metadata from endpoint-specific payloads.
- Keep endpoint capabilities discoverable so the UI does not offer unsupported
  actions.
- Document migration and fallback behavior when one endpoint is unavailable.

### Standards And Rulebook Variability

Planned outcome:
- Let deployments select the standard/rulebook profile that applies to a
  workflow, such as Zenodo-focused, Europeana/EDM-focused, ECCCH-focused, or
  institution-specific profiles.

Open work:
- Version validation profiles.
- Record the active profile in `.hdpc` provenance.
- Show users which profile produced a warning or blocking error.

## Embedded Intelligence

### LLM-Assisted Mapping, Structuring, And Workflows

Planned outcome:
- Add optional embedded intelligence to assist users with metadata mapping,
  file grouping, MSF repair, controlled vocabulary suggestions, and workflow
  planning.

Design constraints:
- AI assistance must remain advisory unless an operator explicitly enables
  automation.
- Users must be able to inspect, reject, and edit suggestions before they affect
  publication state.
- Prompts, model configuration, source context, and accepted suggestions should
  be recorded when they influence metadata or workflow decisions.
- Sensitive data and credentials must not be sent to external AI providers
  unless the deployment policy explicitly allows it.

Open work:
- Define local versus remote model policies.
- Add confidence, citation, and source-evidence fields to generated
  suggestions.
- Add regression fixtures for AI-assisted mapping so workflows remain
  testable without relying on live model output.

## Human-In-The-Loop Design

Planned outcome:
- Make human decision points explicit throughout publication, validation,
  moderation, and compute-heavy workflows.

Required review points:
- metadata mapping and MSF repair
- rights/license/publication decisions
- community append/remove and moderation decisions
- endpoint-specific publish actions
- high-cost HPC allocations and long-running jobs

HPC-specific open work:
- Add maximum input-waiting time policies for interactive or paused HPC-backed
  workflows.
- Release allocations automatically when a user decision times out, while
  preserving enough state to resume safely later.
- Expose countdowns, warnings, and release reasons in the UI and audit log.

## Institutional Collaboration

### Collections And Cross-Institutional Communication

Planned outcome:
- Expand the use of collections as collaboration, review, governance, and
  communication objects.

Open work:
- Define collection ownership, membership, visibility, and moderation policy.
- Support intra-institutional notes, review requests, and status changes.
- Support cross-institutional handoff or request workflows without exposing
  private credentials or unrelated sessions.
- Record decisions and communication events in auditable history.

### Structured Seeding Mechanism

Planned outcome:
- Provide structured, repeatable seeding for institutions, accounts, policies,
  communities, and initial operator state.

Open work:
- Define an input structure for seed files, including schema, validation, dry
  run, and rollback behavior.
- Add clear separation between public seed data and secret provisioning.
- Support invitation flows from the Admin section, for example inviting users to
  join an institution or accept a role.
- Make seeded objects idempotent so repeated deployment does not create
  duplicates.

## Suggested Prioritization

1. Development roadmap and ECCCH-INFINITY rulebook compliance matrix.
2. Record preview and draft management, because this improves review and
   publication governance without requiring a new deployment topology.
3. Enhanced LOD and EDM validation reports, because they strengthen the
   publication quality gate.
4. Cloud transfer and structured seeding, because both improve real deployment
   setup without changing the publication model.
5. Human-in-the-loop HPC timeout/release policy for fair use of shared compute.
6. Collection and institutional communication improvements.
7. Cloud transaction mirroring for audit and recovery.
8. Multi-instance state transfer.
9. Endpoint variability and standards/rulebook profile variability.
10. Broader HPC-Link production integration, after allocation governance and
   fallback behavior are fully documented.
11. Embedded intelligence, after governance, provenance, privacy, and regression
   testing contracts are in place.

## Traceability To Planning Notes

| Planning topic | Document section |
|---|---|
| Compliance to Technical Rulebook v1 of ECCCH-INFINITY | ECCCH-INFINITY Technical Rulebook Alignment |
| Cloud transfer instead of browser upload | Cloud Transfer Instead Of Browser Upload |
| Embedded intelligence for mapping, structuring, and workflows | LLM-Assisted Mapping, Structuring, And Workflows |
| Connecting local, HPC, and web-deployed instances | Connecting Multiple WebHDP Instances |
| Alternatives to Zenodo, ECCCH, or other endpoints | Endpoint Variability |
| Development roadmap | Development Roadmap |
| Human-in-the-loop design and HPC waiting-time limits | Human-In-The-Loop Design |
| Collections and intra-/cross-institutional communication | Collections And Cross-Institutional Communication |
| Structured seeding for institutions and accounts | Structured Seeding Mechanism |

## Documentation And Release Gates

Before any item moves from planned work to release work:

- add or update an architecture decision when the change affects contracts,
  storage, credentials, publication endpoints, or deployment topology
- update the workflow inventory and source-surface coverage
- add operator documentation and failure/recovery guidance
- add tests or verification scripts that prove the new behavior
- update the public documentation and release notes for the target release
