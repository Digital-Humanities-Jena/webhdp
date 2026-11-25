# Third-Party Notices

WebHDP itself is licensed under the European Union Public Licence v. 1.2 or later (`EUPL-1.2`). See `LICENSE`.

Third-party dependencies, standards documents, schemas, and external tools retain their own licenses and terms. This file records the release boundary for the public alpha repository.

## Runtime And Package Dependencies

Python, Node.js, Docker image, and system packages are resolved from their respective package registries or base images. Their license terms are not replaced by the WebHDP license. Lockfiles and manifests are included for reproducibility only.

The frontend build publishes the Google Draco glTF decoder and Binomial Basis Universal transcoder from the pinned Three.js package. Their Apache 2.0 license texts ship with the frontend under `/model-decoders/`. [Draco license](https://github.com/google/draco/blob/gltf_2.0_draco_extension/LICENSE) · [Basis Universal license](https://github.com/BinomialLLC/basis_universal/blob/v1_60/LICENSE)

## Local EDM Validator

The local EDM validator source is not vendored in this repository. WebHDP uses a pinned external checkout from:

`https://github.com/Digital-Humanities-Jena/local-edm-validator.git`

The setup script checks out the pinned commit configured in `.env.example` and initializes its Metis Schema `v15` submodule. Both upstream projects retain their own terms and release process.

## Standards And Reference Documentation

The public alpha repository links to external standards prose instead of vendoring full copies. See `docs/standards_links.md` for upstream EDM, IIIF, METS/MODS, and Zenodo documentation.

The `docs/metsmods/` and `schema_xsds/` materials are runtime validation schemas used to validate WebHDP output offline. They retain the terms of their upstream maintainers.

### Europeana EDM XSD Schemas

The files in `schema_xsds/` follow Europeana's Metis schema archive dated 2026-07-20, also available in the Metis Schema `v15` tag. WebHDP preserves these resources for offline validation with local whitespace normalization. They remain attributable to Europeana and retain their upstream terms. [Europeana schema archive](http://ftp.eanadev.org/schema_zips/europeana_schemas-20260720.zip) · [Metis Schema v15](https://github.com/europeana/metis-schema/tree/v15/src/main/resources/schema_xsds)

### METS/MODS Schemas

The files in `docs/metsmods/` are retained because `services/mets_service.py` uses them for offline METS/MODS validation. The METS schema declares CC0 terms in its embedded documentation. MODS is maintained by the Library of Congress; WebHDP keeps the schema only as an offline validation input.

## HDP Components And External Services

The `external_code/` directory contains WebHDP component manifests and selected local component implementations used by the alpha release. Third-party runtimes such as Blender, Docker base images, validators, and conversion tools retain their own licenses.

For alpha, `fast-renderer` and `any-to-usdz` are first-class optional services because the supported `render` publication path can use them directly. Other HDP Components are installable/evaluation components unless separately released and validated.

### HMSM Studio

The optional mechanical-music components use HMSM Studio, distributed under GPL-3.0-or-later. The local image builder takes an explicit HMSM Studio worktree and packages its processing code, exact dependency requirements, and physical model definitions. The image retains the upstream `LICENSE`, `docs/ATTRIBUTION.md`, and the licence notice for the HMSM-Tools measurements. Component runs emit the build's source commit, worktree changes, and SHA-256 inventory as `hmsm-source.json`. [HMSM Studio source](https://github.com/modavis-project/hmsm-studio)

## Published Zenodo HDP Components

The optional shared runtime in `external_code/zenodo_component_runtime` retains
unmodified published processor, manifest and requirements files for seven
components from the [HDP Components community](https://zenodo.org/communities/hdp-components/records):
OBJ to GLB Converter, HDPC to CSV Exporter, OBJ Statistics Extractor, MTL
Metadata Extractor, GLB Metadata Extractor, File Integrity Validator and Image
Metadata Extractor. Copyright (C) 2025 Dominik Ukolov. The corresponding Zenodo
records declare GPL-3.0-or-later. Source records, versions and published file
checksums are retained in `external_code/zenodo_component_runtime/upstream-records.json`;
the runtime includes the GPL license text and `NOTICE`. WebHDP adapters and
fixes are included as separate source files under the same terms. The
separately installed image includes Blender and Python libraries, each under
its own applicable license. Fast Renderer remains a separately installed
GPL renderer integration. See the [community component guide](docs/guides/zenodo_community_components.md)
for the exact eight-record inventory and source links.

## Fixtures

Root fixtures and `test_data/workflow_fixtures/` media-like files are synthetic generated/minimized WebHDP fixtures. They are intended for scanner, setup, and onboarding tests, not as cultural-heritage sample data.

## Documentation Media

`docs/assets/screen_recordings/` contains curated WebHDP walkthrough recordings referenced by the in-app documentation. `scripts/check_release_assets.py` enforces the alpha allow-list, file-size limit, and reference consistency. If a maintainer cannot confirm provenance for a recording, move it out of the source repository and publish it as an external release asset instead.

## Mesh Optimizer

The optional HPC component integrates [3DOM-FBK/mesh-optimizer](https://github.com/3DOM-FBK/mesh-optimizer), pinned at revision `a1e76f43b9257be5288ad18c52b640c6a3f4829a`, whose repository carries the GNU GPL version 3. See `external_code/mesh_optimizer/UPSTREAM_LICENSE`. Its external runtime includes Blender and other upstream dependencies under their respective licenses; the runtime image is installed separately and is not bundled in WebHDP.

## 3DGeoRef

The optional georeferencing component uses the orthographic renderer from [3DOM-FBK/3DGeoRef](https://github.com/3DOM-FBK/3DGeoRef), pinned at revision `e50e4562b43c0b105d77e417d01fedb5139529a6`, under the BSD-2-Clause license. See `external_code/georeferencer/UPSTREAM_LICENSE`. The separately installed runtime includes Blender, PyTorch, Kornia and the outdoor LoFTR checkpoint under their respective licenses. Runtime images and model weights are not bundled in this source repository.

## Historic reconstruction integration

The portable runtime in
`external_code/historic_reconstruction_runtime` uses COLMAP/pycolmap, NumPy and
Pillow under their respective upstream licences. Container builds install these
dependencies; their source is not copied into this repository.

The six optional research adapters invoke a separately installed
`historic_reconstruction_pipeline` source snapshot and its model dependencies.
The supplied archive did not include a repository licence. Its source, example
datasets and weights are therefore not vendored or redistributed here. Operators
must retain the licences and usage conditions of their separately provisioned
source and weights. The integration evaluation records the archive's identity
and the distinction between the portable baseline and original research code.
