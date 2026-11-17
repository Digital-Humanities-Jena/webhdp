# WebHDP Release Notes

## 0.1.0-alpha.3 - 2026-11-17

### Publication workflows

- Pipeline runs and Zenodo requests preserve operation identities across retries. Use reconciliation to check the remote result when a response is lost. Guided submission restores in-progress drafts and shows records that need corrections before execution.
- Readiness checks account for pipeline input alternatives, dataset scope, metadata requirements, and previously completed work. File selection retains linked metadata source names and keeps derived artifacts distinct from original inputs.
- CPU detail generation for static GLBs checks geometry and preserves the source files. Metadata and validation reports include the provenance of their inputs and outputs.

### Optional components and integrations

- The historic reconstruction catalogue adds 11 installable components for photograph preparation, pair selection, COLMAP reconstruction, georeferencing, and separately provisioned research stages. The research stages require pinned external code, dependencies, and weights. See the [installation and input guide](docs/guides/historic_reconstruction.md) and [research runtime guide](docs/guides/historic_reconstruction_research.md).
- Eight recipes integrate the published Zenodo HDP community components for OBJ conversion and analysis, material, GLB, and image metadata, HDPC export, file integrity validation, and rendering. See the [Zenodo component guide](docs/guides/zenodo_community_components.md).
- Three separately installed [HMSM components](docs/guides/hmsm_components.md) cover piano-roll scan digitization, MIDI interpretation, and MIDI reconstruction.
- Operators can register an existing Slurm GPU job as a private reservation. Approved users can claim it from WebHDP, run supported HPC components, then release the claim without cancelling the scheduler job. See the [live demo guide](docs/guides/prereserved_gpu_demo.md).
- [WebHDP-Link](docs/guides/webhdp_link.md) lets registered applications invoke explicitly published native pipelines, track runs, and download artifacts. It includes scoped credentials, OAuth authorization code with S256 PKCE, hosted processing pages, a JavaScript SDK, and a separate worker. Browser and service integrations require explicit client registration and pipeline publication.

### Security and upgrades

- This release updates vulnerable Python and JavaScript dependencies. Production startup requires a signing key of at least 32 bytes. Use a randomly generated key and keep it out of the repository.
- HPC-Link component inputs are confined to the job's staging area. Cloud staging and Link worker execution apply additional ownership and filesystem checks.
- Back up the installation and apply the database migrations before starting the new backend and workers. The core deployment profile remains available for the predefined publication workflows. See the [upgrade guide](docs/guides/upgrade_alpha3.md).

## 0.1.0-alpha.2 - 2026-09-26

- The installable 3DGeoRef component adds **3D Georeferencing & Preview** for static GLBs paired with reference GeoTIFFs. It produces a placed model, coordinate report, alignment overlay and five Fast Renderer previews. Weak or inconsistent matches fail explicitly; automatic location discovery and absolute elevation assignment are not enabled.
- Mesh Optimizer 1.0.1 preserves material graphs, UVs, colors and normals, avoids texture upscaling, and retains geometry when simplification exceeds the error limit. Invalid and unsupported inputs are rejected before processing.
- Workflow recovery keeps generated artifacts out of the original-file selection and preserves each model's reference bundle. Generated models, reports and previews can be downloaded from their records.
- The installable Mesh Optimizer component adds an HPC **Mesh Optimization & Preview** workflow for static GLB models. It preserves originals, saves optimized derivatives and reports, and renders the derivatives with Fast Renderer. GPU containers use isolated disk scratch space; missing UVs and multi-material inputs are handled before baking.
- Password login is the default. Each user can enable email two-factor authentication after confirming an enrollment code, or disable it with their current password.
- Core pipelines generate CIDOC-CRM RDF/XML and equivalent JSON-LD alongside EDM, IIIF, and METS/MODS. Exports describe the digital dataset without inventing physical-object history.
- Nested MSF-listed models remain separate records, including models that share a buffer. Dependency paths survive HPC staging, and source bundles preserve directory layouts and repeated texture filenames when downloaded from Zenodo.
- The bundled EDM XSD now runs on every validated export. Aggregation elements follow the schema sequence, and the preview distinguishes passed checks from skipped ones.
- HPC-Link service accounts renew bearer tokens automatically. Allocation owners can download their own output artifacts without general filesystem access.
- The renderer honors the configured Blender executable and supports the Blender 4.x STL importer and multiple OBJ material libraries. Missing libraries and unreadable textures produce explicit errors.
- Reruns reuse unpublished Zenodo drafts, restore missing originals, and replace changed artifacts. Concurrent mutations of one session are rejected, while independent sessions can proceed. Expired HPC allocations release queue capacity and can be replaced in one request.
- Guided submission retains its operation identity across lost responses and reconnects even if saving workflow state fails. Metadata selections preserve saved providers and avoid advancing after failed saves.
- Batch previews no longer override other records' file identities. Interrupted metadata retries remain recoverable, unchanged uploaded exports stay uploaded, and record actions exclude validation-blocked files. Current file readiness is shown separately from historical pipeline failures.
- METS identifiers remain valid for Unicode, spaces, and punctuation, including images used as their own previews. Uploaded filenames and content URLs preserve reserved characters.
- ZIP preflight rejects traversal, ambiguous paths, symlinks, encrypted files, unsupported compression, and oversized expansion before queueing work. Windows-style separators are normalized consistently.
- Production draft workflows support individual uploads as well as named dataset directories, while retaining duplicate-record checks.
- A core deployment profile disables unverified optional tools and pipeline authoring. A separate publishing switch permits draft-only operation.
- Backend images build from the frozen dependency lock; frontend dependency security updates are included.

Deployment credentials, scheduler policy, VPN configuration, and operator validation artifacts belong in private deployment profiles outside the public source tree. Pipeline bindings now support `record_source_files` for record-isolated input bundles; the `.hdpc` schema is unchanged.

The deployed component workflows were also tested through public HTTPS, Celery and HPC-Link: two mesh-optimization records and three georeferencing records completed, while an unrelated reference was rejected without derived output. All five resulting GLBs passed independent validation with zero errors or warnings; 25 previews and three alignment overlays decoded successfully. Original checksums were unchanged. Dropbox mirror downloads, private-file access controls, browser pipeline selection and report downloads passed. See the component validation reports for broader input coverage and limitations.

Verification: 768 backend tests, 301 frontend unit tests, 116 HPC-Link tests, 26 georeferencing component tests, and 109 browser tests passed. Live validation covered a fresh deployment, public HTTPS uploads and browser workflow, email 2FA, GPU rendering of glTF/GLB/OBJ/STL/FBX/PLY, shared and nested dependencies, Unicode paths, concurrent submissions, draft retries, and unpublished Sandbox/Production drafts. Downloaded artifacts passed checksum, EDM XSD, METS/MODS XSD, and RDF equivalence checks. Source bundles preserve reconstructable model dependencies. Corrupt textures and unsafe archives are rejected explicitly. Five environment-dependent or browser-specific checks remain intentionally skipped; unverified optional deployment features are disabled.

## 0.1.0-alpha.1 - 2026-05-28

This is the first public alpha repository release for WebHDP.

### Supported Alpha Boundary

- Stable first-release workflows: predefined `render` and `metadata_only` publication paths.
- Local EDM validation: pinned external checkout of `Digital-Humanities-Jena/local-edm-validator` via `make local-edm-validator-setup`.
- Optional local compute services: `fast-renderer` and `any-to-usdz` remain first-class Compose services for workstation-local evaluation.
- Broader installable HDP Components, Pipeline Constructor workflows, HPC/SIF execution, and production HPC-Link operation remain evaluation features unless a deployment validates them separately.

### Release Hygiene

- Public fixtures are synthetic or minimized generated assets.
- Local runtime data, reports, production/research exports, logs, databases, credentials, generated build outputs, and scratch test folders are excluded from the release index.
- Docker and CI validation use `.env.example` safely without overwriting an existing local `.env`.
- Public documentation includes a Docker quickstart, HPC local-mode setup guide, release walkthrough videos, and a consolidated future roadmap.

### Verification Scope

Before publishing this alpha, maintainers should run the checks in `PUBLISHING.md`, including backend tests, frontend tests/build, HPC-Link tests, Compose validation, devcontainer validation, and release image tag checks.
