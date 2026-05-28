# HDP Component Publishing Guide

This guide explains how to publish an HDP Component after it has been built and
validated. It continues from `first_hdp_component.md`, which shows how to turn a
container into a runnable component. This document focuses on the next step:
making that component discoverable, installable, reviewable, citable, and
reproducible for other WebHDP deployments.

Use this guide when:

- your component already has a working `component.yaml` and runner
- the smoke test passes locally or in the target runtime
- you want to share the component with another WebHDP instance
- you need a release record that can be cited in a publication or project report
- you are preparing a curated component index entry for WebHDP administrators

If you have not created the component yet, start with
`docs/development/first_hdp_component.md`.

## Publishing In WebHDP

Publishing an HDP Component does not mean copying Python code into the WebHDP
backend. An HDP Component remains a separate executable package. WebHDP only
imports the manifest contract and registers an execution profile after an
administrator validates and installs the component.

The publishing model has four layers:

| Layer | Purpose | Typical Location |
|---|---|---|
| Source repository | Human review, issues, pull requests, release notes, build instructions | GitHub, Codeberg, GitLab, institutional Git |
| Runtime artifact | The executable thing WebHDP or HPC-Link runs | OCI/Docker registry, local Docker image, HTTPS SIF asset, HPC filesystem path |
| Archival record | DOI-backed preservation and citation | Zenodo record, usually in the HDP Components community |
| Component index | Curated machine-readable discovery for WebHDP installers | HTTPS JSON index or absolute local JSON file |

The important design principle is separation of responsibility:

- Git is for development and review.
- OCI images and SIF files are for execution.
- Zenodo is for archival citation.
- WebHDP's component index is for trusted discovery.
- WebHDP's native registry remains the runtime authority after installation.

This keeps WebHDP from downloading arbitrary code directly from a repository
while still allowing developers to use ordinary Git and release workflows.

## Current Repository Status

The WebHDP repository is not yet published. Until the public repository and
hosted component index exist, use local absolute-path indexes for development
and review:

```env
WEBHDP_COMPONENT_INDEX_SOURCES=/absolute/path/to/webhdp_clean/docs/examples/component-index/index.json
WEBHDP_COMPONENT_INDEX_MIN_TRUST=unknown
```

This allows the full index loading, manifest checksum, compatibility, trust,
and UI workflow to be tested without pretending that public URLs already exist.

After publication, replace local paths with HTTPS index URLs and immutable
release links.

## Publishing States

Use clear states when talking about a component. This avoids confusion between a
component that merely works on one machine and a component that is safe to
install from a curated catalog.

| State | Meaning | Suitable For |
|---|---|---|
| Draft | Manifest and runner are still changing. No external reuse promise. | Local developer work |
| Candidate | Smoke test passes and artifacts can be built, but review is incomplete. | Internal review |
| Experimental | A release exists and may be indexed, but behavior may change. | Early adopters, project-specific tools |
| Community-reviewed | A maintainer has reviewed the manifest, runtime contract, artifacts, license, and verification evidence. | Recommended shared use |
| Trusted | Maintained, reproducible, documented, checksum-pinned, and suitable for production policy. | Production curated installs |
| Deprecated | Still installable for old pipelines, but no longer recommended. | Reproducibility and migration only |

These states map naturally to the index `trust_level` values:

- `unknown`
- `experimental`
- `community-reviewed`
- `trusted`

Production deployments should normally set:

```env
WEBHDP_COMPONENT_INDEX_MIN_TRUST=community-reviewed
```

Use `unknown` only for local development, unpublished fixtures, or private
testing indexes.

## What Must Be Published

A complete published component release should provide:

- `component.yaml`
- runner source code
- Dockerfile or build recipe
- runtime artifact reference
- manifest SHA-256
- Docker digest or SIF SHA-256
- license information
- citation text when relevant
- smoke-test fixture and result
- release notes
- WebHDP compatibility range
- optional SBOM and provenance evidence
- optional Zenodo DOI and concept DOI
- component index entry

The release is incomplete if a WebHDP administrator cannot answer these
questions:

- Which component key and version am I installing?
- Which manifest was reviewed?
- Which executable artifact will run?
- Which Git commit or tag produced that artifact?
- Which WebHDP versions are compatible?
- What license and citation obligations apply?
- What smoke test proves the release is installable?
- What checksum proves I got the expected artifact?

## Component Package Requirements

The package created in `first_hdp_component.md` should remain the foundation.
Before publishing, confirm the component directory has the expected shape:

```text
external_code/
  image_inspector/
    component.yaml
    runner.py
    Dockerfile
    README.md
    LICENSE
```

The minimal files are `component.yaml`, runner code, and a build recipe. A
component intended for external reuse should also include a short `README.md`
that explains:

- what the component does
- expected input file types
- generated output files
- important parameters
- known limitations
- local build command
- smoke-test command or WebHDP install-test description
- license and citation notes

Keep the runner small. It should adapt WebHDP's request/response contract to
the domain tool, not reimplement WebHDP or hide many unrelated workflows behind
one component.

## Manifest Requirements

The manifest is the contract WebHDP imports. Treat it as a public API.

A publishable manifest should contain:

- stable `metadata.name`
- semantic `metadata.version`
- descriptive `metadata.label`
- useful `metadata.description`
- `distribution.tier: external_installable`
- `distribution.bundled_with_webhdp: false`
- `distribution.installation_scope`
- typed `inputs`
- typed `outputs`
- one or more execution profiles
- Playground compatibility when interactive use is intended
- `install.test` for local Docker installs
- `hpc.test` for HPC SIF installs
- license, maintainer, and citation metadata when available

Example distribution block:

```yaml
distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope:
    - local_container
    - hpc_sif
```

Example local Docker profile:

```yaml
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: ghcr.io/example/image-inspector:1.0.0
      entrypoint: [python, /app/runner.py]
```

Example HPC-Link/Singularity profile:

```yaml
execution:
  profiles:
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      image: ""
      entrypoint: [python, /app/runner.py]
```

For HPC installs, leave the SIF path out of the source manifest or keep it as a
placeholder. The installer replaces the profile image with the installed remote
SIF path.

## Versioning Rules

Use the component version to communicate compatibility of behavior, inputs, and
outputs.

Recommended rule:

- Patch version: bug fix that preserves inputs, outputs, and expected meaning.
- Minor version: new optional parameter, new optional output, improved metadata,
  or expanded supported file types.
- Major version: changed required input, removed output, changed output schema,
  changed default behavior in a way that can affect pipelines.

Do not reuse a published component version for a different artifact. If the
runtime image changes after publication, create a new release. WebHDP can merge
local and HPC profiles for the same component version, but those profiles should
be semantically equivalent.

For example, this is acceptable:

- `image_inspector` version `1.0.0`
- local Docker artifact `ghcr.io/example/image-inspector@sha256:...`
- HPC SIF artifact `image-inspector-1.0.0.sif`
- both artifacts produce the same outputs for the same inputs

This is not acceptable:

- `image_inspector` version `1.0.0`
- local artifact returns `image_report`
- HPC artifact returns `metadata_report`

That should be a new version.

## Build Runtime Artifacts

WebHDP does not build runtime artifacts during installation. Build them before
publishing.

For local Docker:

```bash
docker build -t ghcr.io/example/image-inspector:1.0.0 external_code/image_inspector
docker image inspect ghcr.io/example/image-inspector:1.0.0
```

For reproducible catalog entries, prefer digest-pinned references:

```bash
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/example/image-inspector:1.0.0
```

The index entry should store both:

- Docker image reference, preferably with `@sha256:...`
- Docker digest

For HPC SIF:

```bash
apptainer build image-inspector-1.0.0.sif docker-daemon://ghcr.io/example/image-inspector:1.0.0
shasum -a 256 image-inspector-1.0.0.sif
```

Publish the SIF to one of:

- HTTPS release asset URL ending in `.sif`
- absolute path readable by the HPC-Link user

For shared indexes, HTTPS SIF assets are easier to verify and document. For
private institutional deployments, an absolute HPC path may be more practical.

## Validate Before Release

Run the manifest validator from the repository root:

```bash
uv run python scripts/validate_hdp_components.py external_code/image_inspector
```

Run all component checks:

```bash
make hdp-components-check
```

For stricter release review:

```bash
uv run python scripts/validate_hdp_components.py external_code/image_inspector --strict-warnings
```

A release candidate should not be published while the validator reports errors.
Warnings may be acceptable for early experimental work, but they should be
explained in the release notes or review record.

## Smoke Tests

Every published component should provide at least one tiny smoke test.

Local Docker smoke tests use `install.test`:

```yaml
install:
  test:
    files:
      - name: sample.ppm
        content: |
          P3
          1 1
          255
          255 0 0
    inputs:
      input_file: sample.ppm
    parameters: {}
```

HPC SIF smoke tests use `hpc.test`:

```yaml
hpc:
  test:
    files:
      - name: sample.ppm
        content: |
          P3
          1 1
          255
          255 0 0
    inputs:
      input_file: sample.ppm
    parameters: {}
```

Keep smoke tests small. They prove the artifact starts, reads the request,
writes outputs, and returns a response. They are not a substitute for full
scientific validation.

For binary fixtures, use `content_base64`.

## Git Release Workflow

Use a Git-like system for source review and release history. GitHub, Codeberg,
GitLab, and institutional Git servers all work as long as the release metadata
is stable and accessible.

Recommended workflow:

1. Create or update the component in a branch.
2. Run local validation and smoke tests.
3. Open a pull request or merge request for review.
4. Confirm manifest fields, license, citation, artifact build, and test
   evidence.
5. Merge the reviewed change.
6. Tag the exact source commit.
7. Build runtime artifacts from that tag.
8. Publish release assets.
9. Record checksums.
10. Add or update the component index entry.
11. Archive the release in Zenodo when the component is stable enough to cite.

Tag naming should be predictable:

```text
image-inspector-v1.0.0
```

or, for a repository that contains only one component:

```text
v1.0.0
```

The index entry should store both tag and commit. Tags are human-friendly;
commits are precise.

## Zenodo Archival Workflow

Zenodo is not the primary installer. It is the archival and citation layer.

Use Zenodo when:

- the component is stable enough to cite
- a project deliverable requires a DOI
- the release should be preserved independently from a Git host
- the component wraps research software, a model, or a workflow that needs
  scholarly attribution

Recommended Zenodo record contents:

- release archive from the Git tag
- `component.yaml`
- release notes
- Docker digest and SIF checksum
- license
- citation text
- maintainer contact
- related identifiers for wrapped software
- optional SBOM/provenance files

If using the HDP Components Zenodo community, submit stable releases there after
review. Keep the Zenodo DOI and concept DOI in the component index entry.

The DOI identifies the archived release. The concept DOI identifies the series
of releases.

## Component Index

The component index is the trusted discovery mechanism used by the WebHDP
installer. It is a JSON document with schema:

```text
webhdp.component-index.v1
```

The formal schema is:

```text
docs/schemas/webhdp_component_index_v1.schema.json
```

The local example fixture is:

```text
docs/examples/component-index/index.json
```

Index sources are configured by administrators:

```env
WEBHDP_COMPONENT_INDEX_SOURCES=https://example.org/webhdp-components/index.json
WEBHDP_COMPONENT_INDEX_TIMEOUT_SECONDS=15
WEBHDP_COMPONENT_INDEX_CACHE_TTL_SECONDS=900
WEBHDP_COMPONENT_INDEX_MIN_TRUST=community-reviewed
```

`WEBHDP_COMPONENT_INDEX_SOURCES` accepts comma-separated or newline-separated
HTTPS URLs and absolute local JSON paths. Remote sources must use HTTPS.

## Example Index Entry

This example uses the `image_inspector` component from
`first_hdp_component.md`.

```json
{
  "schema": "webhdp.component-index.v1",
  "generated_at": "2026-05-27T00:00:00Z",
  "components": [
    {
      "component_key": "image_inspector",
      "version": "1.0.0",
      "label": "Image Inspector",
      "description": "Extracts basic image facts for cultural heritage image files.",
      "category": "Image QA",
      "tags": ["image", "qa", "metadata"],
      "trust_level": "community-reviewed",
      "manifest": {
        "url": "https://example.org/components/image_inspector/1.0.0/component.yaml",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      "source": {
        "url": "https://codeberg.org/example/image-inspector",
        "tag": "image-inspector-v1.0.0",
        "commit": "0123456789abcdef0123456789abcdef01234567"
      },
      "release": {
        "url": "https://codeberg.org/example/image-inspector/releases/tag/image-inspector-v1.0.0",
        "tag": "image-inspector-v1.0.0",
        "assets": [
          {
            "name": "image-inspector-1.0.0.sif",
            "url": "https://example.org/components/image_inspector/1.0.0/image-inspector-1.0.0.sif",
            "media_type": "application/vnd.sylabs.sif",
            "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        ]
      },
      "zenodo": {
        "doi": "10.5281/zenodo.1234567",
        "concept_doi": "10.5281/zenodo.1234560",
        "record_url": "https://zenodo.org/records/1234567"
      },
      "compatibility": {
        "webhdp_min": "0.1.0",
        "webhdp_max": "1.0.0"
      },
      "license": "MIT",
      "citation": "Image Inspector contributors (2026). Image Inspector HDP Component 1.0.0.",
      "artifacts": {
        "docker": {
          "image": "ghcr.io/example/image-inspector@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "sbom_url": "https://example.org/components/image_inspector/1.0.0/sbom.json",
          "provenance_url": "https://example.org/components/image_inspector/1.0.0/provenance.intoto.jsonl"
        },
        "sif": {
          "source": "https://example.org/components/image_inspector/1.0.0/image-inspector-1.0.0.sif",
          "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        }
      }
    }
  ]
}
```

Important details:

- `component_key` and `version` must match the manifest metadata.
- `manifest.url` may be relative to the index file for local or hosted static
  indexes.
- `manifest.sha256` is strongly recommended. WebHDP rejects mismatches.
- `trust_level` is compared with the deployment's configured minimum.
- `compatibility.webhdp_min` and `compatibility.webhdp_max` are enforced.
- SBOM, provenance, release, and Zenodo record URLs must use HTTPS.
- `artifacts.docker.image` should be digest-pinned for production use.
- `artifacts.sif.sha256` lets HPC-Link verify the installed SIF.

## Compatibility Ranges

Use compatibility metadata to prevent accidental installation into an
unsupported WebHDP version:

```json
{
  "compatibility": {
    "webhdp_min": "0.1.0",
    "webhdp_max": "1.0.0"
  }
}
```

Set `webhdp_min` when the component relies on a manifest field, installer
feature, execution profile, or Playground behavior introduced in a specific
WebHDP release.

Set `webhdp_max` when a known future breaking change requires a newer component
release.

Do not leave compatibility empty for production-trusted releases unless the
component has intentionally broad compatibility.

## Trust Levels

Use trust levels conservatively:

| Trust Level | Meaning |
|---|---|
| `unknown` | Local/private entry with no review claim. Useful for unpublished testing only. |
| `experimental` | Runs and has artifacts, but the interface or output may change. |
| `community-reviewed` | Manifest, artifacts, license, checksums, and smoke-test evidence were reviewed. |
| `trusted` | Recommended production release with maintained source, pinned artifacts, citation metadata, and clear compatibility. |

Raising trust level is a review action. It should not happen automatically just
because a component has a Git tag.

## Direct Git Retrieval

Direct retrieval from GitHub, Codeberg, GitLab, or another Git-like platform is
useful during development, but it should not be the production install path.

Allowed developer workflow:

1. Clone the component repository.
2. Inspect or edit the component locally.
3. Validate the local manifest.
4. Build or pull the runtime artifact.
5. Use custom manifest mode in the HDP Component Installer.

Recommended production workflow:

1. Review the Git release.
2. Build and publish immutable artifacts.
3. Archive stable releases in Zenodo.
4. Add a curated index entry.
5. Install through the WebHDP catalog.

This avoids turning WebHDP into a generic remote code downloader. The installer
should discover curated releases, not arbitrary repository branches.

## Local Unpublished Index Workflow

Until the public repository and hosted index exist, test the publishing system
with an absolute local index path:

```bash
MANIFEST=/absolute/path/to/component.yaml
shasum -a 256 "$MANIFEST"
```

Create or update an index JSON file:

```json
{
  "schema": "webhdp.component-index.v1",
  "components": [
    {
      "component_key": "image_inspector",
      "version": "1.0.0",
      "trust_level": "experimental",
      "manifest": {
        "url": "/absolute/path/to/component.yaml",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      "artifacts": {
        "docker": {
          "image": "webhdp-image-inspector:local"
        }
      }
    }
  ]
}
```

Configure WebHDP:

```env
WEBHDP_COMPONENT_INDEX_SOURCES=/absolute/path/to/index.json
WEBHDP_COMPONENT_INDEX_MIN_TRUST=unknown
```

Then open Tools -> HDP Component Installer and choose `source=remote` or the
Remote indexes filter. This exercises the same code path that a future HTTPS
index will use.

## Administrator Installation Flow

After a component is in a configured index:

1. Open Tools -> HDP Component Installer.
2. Select the install strategy:
   - `local_container` for Docker-backed local execution.
   - `hpc_sif` for HPC-Link/Singularity execution.
3. Choose the catalog source:
   - Local catalog
   - Remote indexes
   - All sources
4. Select the component card.
5. Review trust level, Git link, release link, Zenodo DOI, manifest checksum,
   Docker digest, and SIF checksum.
6. Confirm or provide the artifact source.
7. Validate the package.
8. Install the component.
9. Run the smoke test.
10. Use the component in Playground or Pipeline Constructor.

The installation record stores catalog provenance such as `catalog_ref`,
`trust_level`, Git metadata, release metadata, Zenodo metadata, checksums,
license, citation, SBOM URL, and provenance URL.

## API Publishing And Installation Checks

List catalog entries:

```bash
curl -G "$BASE_URL/tools/hdp-components/catalog" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "install_strategy=local_container" \
  --data-urlencode "source=remote"
```

Inspect index diagnostics:

```bash
curl -G "$BASE_URL/tools/hdp-components/catalog/diagnostics" \
  -H "Authorization: Bearer $TOKEN"
```

Validate a selected indexed entry:

```bash
curl -X POST "$BASE_URL/tools/hdp-components/validate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "install_strategy": "local_container",
    "manifest_text": "metadata:\n  name: image_inspector\n  version: \"1.0.0\"\n...",
    "container_image": "ghcr.io/example/image-inspector@sha256:...",
    "docker_digest": "sha256:...",
    "catalog_ref": {
      "source": "https://example.org/webhdp-components/index.json",
      "component_key": "image_inspector",
      "version": "1.0.0",
      "manifest_url": "https://example.org/components/image_inspector/1.0.0/component.yaml"
    },
    "trust_level": "community-reviewed"
  }'
```

For HPC SIF installs, provide:

```json
{
  "install_strategy": "hpc_sif",
  "sif_source": "https://example.org/components/image_inspector/1.0.0/image-inspector-1.0.0.sif",
  "sif_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Do not run live HPC acceptance tests while another WebHDP instance has an
active HPC job. Use mocked/local tests until the queue is clear.

## Review Checklist

Before adding a release to a curated index, review:

- Manifest parses and passes `scripts/validate_hdp_components.py`.
- `metadata.name` is stable and machine-friendly.
- `metadata.version` has not been reused for a different artifact.
- Inputs and outputs are typed and documented.
- Required parameters have defaults or clear labels.
- Runner reads `WEBHDP_COMPONENT_REQUEST`.
- Runner writes `WEBHDP_COMPONENT_RESPONSE` on success and expected failures.
- Runner writes generated files only under `WEBHDP_OUTPUT_DIR`.
- Docker image or SIF artifact is built from the tagged source.
- Docker digest or SIF SHA-256 is recorded.
- Smoke-test fixture is small and representative.
- Local Docker profile and HPC SIF profile are semantically equivalent when
  they share the same component version.
- License permits the intended reuse.
- Citation text covers wrapped tools, models, and datasets.
- Release notes describe user-visible changes.
- Compatibility range is set.
- Index URLs use HTTPS except absolute local paths used for unpublished testing.
- Trust level matches the actual review evidence.

## Maintainer Checklist

For each release:

1. Validate the manifest.
2. Build runtime artifacts from a clean tag.
3. Run the local smoke test when local Docker is supported.
4. Run mocked/local HPC-Link contract tests when HPC SIF is supported.
5. Run live HPC acceptance only when HPC resources are available.
6. Compute checksums.
7. Publish release notes and artifacts.
8. Archive in Zenodo if the release is stable.
9. Update the component index.
10. Verify the index appears in WebHDP catalog diagnostics.
11. Install from the catalog in a test WebHDP instance.
12. Record any known limitations.

## Deprecation And Removal

Do not delete old index entries casually. Existing pipeline runs and published
research may need to reconstruct older component versions.

Prefer this sequence:

1. Mark the old release as deprecated in release notes or index metadata.
2. Publish a replacement version.
3. Keep the old manifest and checksums available.
4. Remove from production indexes only when administrators agree that new
   installs should be blocked.
5. Keep Zenodo archival records intact.

If a release has a security issue, remove it from trusted indexes quickly, but
keep a private audit record explaining why.

## Common Problems

### The component appears in Git but not in WebHDP

Git publication is not enough. Add the release to a configured component index,
or use custom manifest mode for development.

### The index entry is ignored

Check:

- schema is `webhdp.component-index.v1`
- source path is HTTPS or absolute local path
- manifest URL resolves
- manifest SHA-256 matches
- trust level meets `WEBHDP_COMPONENT_INDEX_MIN_TRUST`
- compatibility range includes the running WebHDP version
- SBOM/provenance/release URLs use HTTPS

Use:

```bash
curl -G "$BASE_URL/tools/hdp-components/catalog/diagnostics" \
  -H "Authorization: Bearer $TOKEN"
```

### Docker install validation fails

Confirm the image exists on the machine that runs the WebHDP backend or worker:

```bash
docker image inspect ghcr.io/example/image-inspector:1.0.0
```

Also check the deployment allowlist:

```env
WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST=ghcr.io/example/*
```

### HPC SIF validation fails

Check that:

- the SIF URL uses HTTPS and ends with `.sif`, or the remote path is absolute
- the SIF is readable by the HPC-Link user
- the checksum matches
- Singularity or Apptainer is available
- HPC-Link is reachable

Do not debug with live HPC acceptance while another active HPC job is running
for a different WebHDP instance.

### The smoke test passes but real data fails

The smoke test only verifies minimal runtime integration. Add separate
scientific or domain validation fixtures for real behavior. Do not turn the
install smoke test into a large benchmark.

## Publication Decision Table

| Question | If Yes | If No |
|---|---|---|
| Is the component only for one developer machine? | Use local custom manifest or local index. | Prepare a reviewed release. |
| Should other WebHDP instances discover it? | Add it to a component index. | Keep it out of curated indexes. |
| Does the release need scholarly citation? | Archive in Zenodo and record DOI. | Git release plus checksums may be enough. |
| Does it run large jobs or need institutional resources? | Publish SIF and use `hpc_sif`. | Local Docker may be sufficient. |
| Is it production-ready? | Use `community-reviewed` or `trusted`. | Use `experimental` or keep it private. |
| Did behavior or output schema change? | Bump component version. | Patch release may be enough. |

## End-To-End Publishing Checklist

Use this as the final release gate:

- Component package exists and follows the runtime contract.
- Manifest is validated.
- Runner handles success and failure responses.
- Docker image and/or SIF artifact is built.
- Artifact checksum is recorded.
- Smoke test passes in supported non-live environments.
- Live HPC test is scheduled only when HPC resources are clear.
- Git tag points to the reviewed source.
- Release notes are written.
- License and citation metadata are clear.
- Zenodo record exists when DOI archival is required.
- Index entry is created with manifest SHA-256, artifact checksums, source,
  release, compatibility, and trust metadata.
- Index diagnostics in WebHDP show the source as configured and cached.
- Catalog installation works in a test WebHDP instance.
- Playground or Pipeline Constructor can select the installed component.

## Related References

- `docs/development/hdp_component_manifest_specification.md`
- `docs/development/first_hdp_component.md`
- `docs/guides/hdp_component_hpc_installation.md`
- `docs/schemas/webhdp_component_index_v1.schema.json`
- `docs/examples/component-index/index.json`
- `docs/workflows/3d-hdp-component-lifecycle.md`
- `docs/architecture/pipeline_platform_contract.md`
- `external_code/gltf_validator/component.yaml`
