# Published Zenodo community components

The [HDP Components community](https://zenodo.org/communities/hdp-components/records)
returned eight published records when checked on 17 November 2026. This
collection is separate from WebHDP's eleven historic reconstruction components.
Seven published components use the shared, separately installed runtime in
`external_code/zenodo_component_runtime`; Fast Renderer uses WebHDP's existing
renderer service integration.

| Published component | Source record | WebHDP input | Returned artifacts |
|---|---|---|---|
| Fast Renderer | [17622912](https://zenodo.org/records/17622912), v0.1.0 | `input_files`, or `input-dir` | Rendered image directory |
| OBJ to GLB Converter | [16995481](https://zenodo.org/records/16995481), v0.1.0 | `input_file`: OBJ or scene ZIP; optional `dependency_files` | `model_file` GLB, `report` JSON |
| HDPC to CSV Exporter | [16995063](https://zenodo.org/records/16995063), v0.1.0 | `input_file`: `.hdpc` SQLite database | `csv_file`, `export_report` JSON |
| OBJ Statistics Extractor | [16993382](https://zenodo.org/records/16993382), v0.1.0 | `input_file`: OBJ or scene ZIP; optional `dependency_files` | `report` JSON |
| MTL Metadata Extractor | [16993305](https://zenodo.org/records/16993305), v0.1.0 | `input_file`: OBJ, MTL, or scene ZIP | `metadata_report` JSON |
| GLB Metadata Extractor | [16993202](https://zenodo.org/records/16993202), v0.1.0 | `input_file`: GLB, glTF, or scene ZIP | `metadata_report` JSON |
| File Integrity Validator | [16993089](https://zenodo.org/records/16993089), v0.1.0 | `input_file`: staged file | `validation_report` JSON |
| Image Metadata Extractor | [16944352](https://zenodo.org/records/16944352), v0.1.1 | `input_file`: JPEG, PNG, TIFF, GIF, WebP, or BMP | `metadata_report` JSON |

The seven shared-runtime adapter manifests have their own versions: `1.0.1`,
except Image Metadata Extractor `1.1.1`.
Converter `1.0.1` fixes the image packaging so Debian Blender's system Python
has NumPy; installing NumPy only for the separate Python 3.12 contract runner
does not make it available to Blender. The Fast Renderer service integration
uses adapter version `0.1.1`. The previous image extractor script remains available
to already pinned legacy manifests; new installations use the published
processor through the container contract.

## Install locally

Run these commands from the WebHDP repository root:

```bash
docker build --platform linux/amd64 --tag webhdp-zenodo-components:local external_code/zenodo_component_runtime
.venv/bin/python scripts/validate_hdp_components.py external_code/validate_file_integrity external_code/hdpc_exporter external_code/obj_to_glb_converter external_code/obj_statistics_extractor external_code/mtl_metadata_extractor external_code/glb_metadata_extractor external_code/image_metadata_extractor
```

The image includes Blender, NumPy for Blender's system Python, and pinned
packages for the separate contract-runner Python. The build performs a real
Blender GLB export to check the exporter dependencies. Apple Silicon can run
the Linux x86-64 image with Docker Desktop emulation, which adds processing time.
The development tag is a build reference; installation resolves an immutable
image identity for execution and saved pipelines. The installer also retains
that image under a content-derived local tag before registration. This prevents
rebuilding the development tag from orphaning a saved OCI image-index identity.
Installation fails if the retention tag cannot be created.

In **Tools → HDP Component Installer**, select **Local Docker** and install the seven
components from the local catalog. Run each installation test, then open its
**Playground**, select a staged source file, and inspect both the returned
artifacts and the report's values. Local execution requires
`WEBHDP_DEPLOYMENT_MODE=local` and `WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true` under
the existing deployment policy. The processing containers run without network
access and do not require a GPU.

Native Docker runs apply declared CPU/memory limits and the shorter of the
component and requested deadlines. Docker startup itself can be slow. If a
client times out while the daemon is still creating a container, immediate
absence does not prove cancellation. WebHDP attempts removal and reports the
invocation's container name with `cleanup_status: unconfirmed` when removal
cannot be confirmed; reconcile that specific container before retrying.

Fast Renderer remains a separate optional service. See
[Fast Renderer configuration](../renderer_configuration.md) for its local
service and HPC policy. Building the shared image does not start or install
the renderer service.

## Pipelines and profiles

Eight recipes are registered only when all referenced immutable local profiles
are available. Existing saved recipes and their component snapshots are
preserved on reimport and restart.

For installations made before image retention was added, build the corrected
image and install the current component patch versions. In Pipeline Constructor,
create and activate new versions of the affected recipes, selecting the new
component versions while preserving their inputs, parameters, and artifact
bindings. The conversion/inspection recipe must select both converter `1.0.1`
and GLB metadata extractor `1.0.1`. Run readiness and execution again.
Installation deliberately does not rewrite saved recipes or prior run snapshots.
Earlier pins remain recorded, but an image orphaned by a previous development-tag
rebuild may no longer exist locally; a recorded digest alone is not image storage.

| Recipe identifier | Steps |
|---|---|
| `zenodo_validate_file_integrity` | File integrity validation |
| `zenodo_hdpc_exporter` | HDPC CSV export |
| `zenodo_obj_to_glb_converter` | OBJ to GLB conversion |
| `zenodo_obj_statistics_extractor` | OBJ geometry statistics |
| `zenodo_mtl_metadata_extractor` | Material metadata extraction |
| `zenodo_glb_metadata_extractor` | GLB metadata extraction |
| `zenodo_image_metadata_extractor` | Image metadata extraction |
| `zenodo_obj_to_glb_and_inspect` | OBJ conversion, then inspect the returned GLB |

The seven standalone recipes bind the record's source file to `input_file`.
The combined recipe binds the converter's `model_file` artifact to the
extractor, preserving the source/output relationship. Each source model bundle
represents one record. Choose **Pipeline Constructor** to inspect the mappings
or create an edited version. These source-only recipes do not require a
publication metadata draft. A recipe that binds record metadata, writes metadata
fields, or includes publication steps retains the metadata requirement.

All seven manifests also declare `hpc_singularity` profiles for a separately
installed SIF. Supply the SIF and its SHA-256 through **HPC SIF** and verify the
installation on the target system. The supplied recipes select `local_docker`;
an HPC recipe must explicitly select the installed HPC profile. A saved
component version cannot be silently repinned: use a new manifest version for
a different installed runtime if the earlier one is already referenced.
An HPC profile declaration does not install or validate that runtime. Run each
selected profile on the target cluster and verify the returned artifacts before
using it for production data. Local acceptance does not cover a different SIF.

## Input layouts and interpretation

For OBJ/MTL scenes, a ZIP should contain one primary OBJ, its referenced MTL
files, and textures at the original relative paths. The MTL extractor also
accepts a direct material file or a bundle containing one MTL and no OBJ.
For glTF, include one primary GLB/glTF and its relative resource files.
Absolute, remote, escaping, linked, and ambiguous bundle paths are rejected.
An image input is a single image, not a ZIP.

MTL extraction reports missing materials/textures as metadata. Check the
warnings and texture `exists` fields; successful extraction does not promise
that every dependency exists. The adapter fixes relative resolution from
nested material folders and texture filenames containing spaces.

OBJ statistics describe the geometry in the input's own units. Enclosed
volume is reported only for closed, consistently oriented surfaces. GLB
metadata bounds use declared mesh-local accessor values; scene transforms
are not applied. Its `approximate_volume` is the axis-aligned bounding-box
product, not enclosed mesh volume. Missing bounds are null. Triangle counts
handle indexed and non-indexed triangle, strip, and fan primitives. Metadata
extraction is not a full glTF conformance validator.

Image extraction preserves the source bytes. By default it omits GPS from the
report, filters email/address text in selected EXIF fields, includes technical
EXIF and a SHA-256, and filters unreadable maker notes. Text filtering is
heuristic; the report and original image must not be treated as anonymized.
Privacy options affect the report only. Pillow's public EXIF access also
preserves supported PNG/TIFF EXIF.

## Integrity verdicts and HDPC exports

The integrity component can finish successfully with `is_valid: false`.
This means the validator ran and detected a bad file. Inspect the report's
verdict and errors before using the file in a later workflow.

Supported checks include image verification/decoding, finite JSON syntax,
glTF asset version, GLB header/chunk lengths, ZIP CRCs, WAV sample length,
Mutagen header/metadata parsing for MP3, FLAC, OGG, Opus, M4A, AAC and AIFF,
SQLite `quick_check`, and strict PDF parsing/page-tree access. PDF pages are
not rendered; compressed audio signals are not decoded; SQLite checks do not validate application schema or foreign
keys; GLB checks are not full semantic validation. Other nonempty formats
receive readability-only coverage with an explicit warning. The validator
does not change source permissions or quarantine flags.

The adapter selects its checker by filename extension and labels the reported
MIME type as an extension-based guess. This differs from the published
processor's `python-magic` detection. A file with an unrecognized extension
receives readability-only coverage even if its content belongs to a known
format. Audio metadata inputs are limited to 512 MiB; unknown or malformed
audio streams receive a negative verdict. Metadata parsing does not establish
that every compressed sample decodes successfully. Very short ADTS AAC streams
can receive a negative verdict when Mutagen cannot collect the minimum three
frames it requires for stream detection.

The HDPC exporter requires `project_info` and `source_files` tables. It opens
the staged SQLite database read-only, selects existing tables and columns,
parameterizes status/date values, and verifies that the source checksum is
unchanged. Use a complete, closed database snapshot when staging a file.

Export modes are `files_overview`, `zenodo_records`, `metadata_export`,
`project_summary`, `api_log`, and `custom`. Optional status and inclusive date
filters apply only when their table has compatible columns. `columns` is a
comma-separated list of existing column names; empty means all columns.
Project summary counts are grouped by project when the schema provides
project IDs. `max_rows` defaults to 10,000, with a maximum of 100,000; the
report explicitly marks truncation. CSV headers and text cells that could
be spreadsheet formulas are prefixed with an apostrophe; BLOBs are hexadecimal.
These exports are review artifacts, not database round-trip backups.

## Source and verification

The seven published processors, manifests, and requirements are retained
unchanged in `external_code/zenodo_component_runtime/upstream/`. Their source
record/version and published checksums are listed in `upstream-records.json`.
The adjacent `LICENSE` and `NOTICE` retain GPL-3.0-or-later attribution; WebHDP's
adapters are separate source files with documented fixes. Runtime images and
dependencies retain their own applicable licenses.

Meaningful regression coverage lives in `tests/test_zenodo_metadata_components.py`,
`tests/test_zenodo_data_components.py`, and the OBJ runtime/integration tests.
Synthetic measured fixtures establish known dimensions, triangle counts,
material dependencies, privacy behavior, export counts and rejection cases.
Installation tests, native application execution, screenshots, and Draco
execution are distinct evidence levels; none should be inferred merely from
manifest availability or a passing unit test.
