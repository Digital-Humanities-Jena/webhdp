# Zenodo component runtime

This separately installed GPL-3.0-or-later runtime adapts seven published HDP
Components to WebHDP's file contract. Fast Renderer is the eighth component in
the 6 November 2026 community inventory and uses the existing service
integration. See the [operator guide](../../docs/guides/zenodo_community_components.md)
for source records, all eight recipes, supported inputs, installation and
validation limits.

Build from the WebHDP repository root:

```bash
docker build --platform linux/amd64 --tag webhdp-zenodo-components:local external_code/zenodo_component_runtime
```

The image has a pinned Python base, fixed Python package versions, and Blender
from the Debian base's package repository. The complete image identity is
resolved and recorded by the WebHDP installer. Building from the same Dockerfile
at a later date can resolve different Debian package revisions; use the
installed immutable image identity when reproducing a run.

Adapter versions are `1.0.1` except image metadata extractor `1.1.1`.
The converter patch installs NumPy for Debian Blender's
system Python as well as the separate contract-runner Python environment.
A genuine GLB export during the image build verifies that dependency boundary.
The installer retains verified images under content-derived local tags before
registering their immutable identities. Existing installs made before retention
was added need new component patch versions and explicitly updated recipe
versions if rebuilding the development tag orphaned their old OCI index.
Retain previous recipe versions and run snapshots; do not silently substitute
a different image for their recorded identities. See the operator guide for
the upgrade sequence.

The common command is:

```text
python /app/component_runner.py COMPONENT --webhdp-input REQUEST.json --webhdp-output-dir OUTPUT --webhdp-result RESULT.json
```

`COMPONENT` is `validate_file_integrity`, `hdpc_exporter`,
`obj_to_glb_converter`, `obj_statistics_extractor`, `mtl_metadata_extractor`,
`glb_metadata_extractor`, or `image_metadata_extractor`. Requests contain
`inputs` and `parameters` objects. Inputs must resolve to staged files within
`WEBHDP_INPUT_DIR` (default `/inputs`). Every run requires a fresh output
directory. Successful results expose named `outputs`, SHA-256-tagged
`artifacts`, and measured `summary` values. Failures produce a structured
failed result and a nonzero exit status. The integrity stage's negative file
verdict is an ordinary successful execution with `summary.is_valid: false`.

The seven physical component manifests live in their individual sibling
directories. They declare offline `local_docker` and operator-installed
`hpc_singularity` profiles. The shared image needs no GPU. HPC profiles still
require installation and acceptance on their target runtime.

## Source adaptations

The original processor/manifests/requirements bytes remain in `upstream/`.
`upstream-records.json` records DOI, version, license, attribution, and published
checksums. `NOTICE` and `LICENSE` accompany the source and image.

`metadata_components.py` invokes the original three metadata processor classes
through reviewed adapters: confined resource resolution, nested MTL folders,
texture options and names containing spaces, corrected triangle counts,
finite missing-bound values, portable Pillow EXIF access and optional GPS
withholding. Reports identify the source DOI and exact processor SHA-256.

`data_components.py` implements read-only adaptations of the published
integrity and HDPC export behavior. It omits the original permission/quarantine
changes and replaces interpolated export SQL with checked identifiers and
parameterized filters. CSV formula mitigation includes headers and data cells.
The source database checksum, export truncation and exact validation coverage
remain visible in reports.

Integrity dispatch uses filename extensions, with the reported MIME type
explicitly an extension-based guess instead of the upstream `python-magic`
classification. Mutagen 1.48.1 parses supported non-WAV audio headers and
metadata with a 512 MiB input cap; compressed signals are not decoded.

`obj_components.py` and `obj_blender.py` provide real Blender conversion and
measured OBJ geometry analysis with staged dependency resolution. Blender
conversion embeds the resulting GLB resources. Reports distinguish usable
closed-surface volume from measurements that cannot establish volume.

`common.py` validates staging boundaries and unpacks bounded archives without
path traversal, links or colliding filenames. `component_runner.py` stages
private temporary outputs, copies declared artifacts to the run directory,
and writes the WebHDP response contract.

Privacy filters do not rewrite image files or guarantee anonymization.
Metadata extraction does not prove glTF conformance. GLB reported volume is
the bounding-box product. Integrity coverage and HDPC export limitations are
described in the operator guide and emitted reports.
