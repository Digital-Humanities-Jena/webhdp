# HDP Component Manifest Specification

This specification defines the WebHDP `component.yaml` manifest contract for
HDP Components. It is the normative developer reference for creating,
reviewing, publishing, validating, installing, and running manifest-backed
components in WebHDP.

For a hands-on walkthrough, start with `first_hdp_component.md`. For release and
distribution workflow, use `hdp_component_publishing_guide.md`. This document
answers the more precise question: "What may or must be present in
`component.yaml`, and what does WebHDP do with it?"

## Status

Current manifest contract:

- Manifest file name: `component.yaml`
- Manifest format: YAML object
- Current component schema marker used by examples: `0.1.0-alpha.1`
- Formal JSON Schema companion:
  `docs/schemas/webhdp_component_manifest_v0_1_0_alpha_1.schema.json`

The JSON Schema can validate the shape of a parsed YAML document, but the
runtime authority remains WebHDP's backend normalization and validation code:

- `schemas/native_pipeline_schemas.py`
- `services/native_pipeline_system.py`
- `scripts/validate_hdp_components.py`

The schema and this document are intentionally a little stricter and clearer
than the raw Pydantic model where best practice requires it. WebHDP currently
allows some extra keys for forward compatibility.

## Normative Language

The words below have their usual RFC-style meaning:

- **MUST** means a requirement.
- **MUST NOT** means a prohibited form.
- **SHOULD** means strongly recommended unless there is a documented reason.
- **MAY** means optional.

## Concept

An HDP Component is a separately executable processing package. WebHDP does not
import the component's code as Flask or Vue application code. Instead, WebHDP
reads `component.yaml`, normalizes it into the native component registry, and
uses the declared execution profile to run the component through an adapter.

The manifest defines:

- stable identity
- typed inputs
- typed outputs
- optional typed parameters
- execution profiles
- installation strategy metadata
- Playground and Pipeline Constructor UI metadata
- smoke-test metadata
- compatibility and distribution metadata

The runtime artifact is separate from the manifest. For local execution it is
usually a Docker image. For HPC execution it is usually a Singularity/Apptainer
SIF file installed through HPC-Link.

## File Location

For repository-local components, the expected layout is:

```text
external_code/
  component_name/
    component.yaml
    runner.py
    Dockerfile
```

The component directory SHOULD match `metadata.name`. The validator warns when
it does not.

## Minimal Manifest

This is the smallest useful external local-container manifest:

```yaml
metadata:
  name: image_inspector
  label: Image Inspector
  description: Extracts basic image facts.
  version: "1.0.0"
  component_schema: "0.1.0-alpha.1"

distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope: [local_container]

inputs:
  - name: input_file
    label: Input Image
    type: file_path
    required: true

outputs:
  - name: image_report
    label: Image Report
    type: file_path

execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: webhdp-image-inspector:local
      entrypoint: [python, /app/runner.py]

compatibility:
  playground:
    enabled: true

install:
  strategies:
    - id: local_container
      runtime: docker
      profile: local_docker
      image: webhdp-image-inspector:local
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

## Top-Level Fields

| Field | Required | Type | Purpose |
|---|---:|---|---|
| `metadata` | Yes | object | Stable identity and descriptive metadata |
| `sources` | No | object | Source repository or upstream references |
| `distribution` | Recommended for external components | object | Installability and bundling metadata |
| `structure` | No | object | Required repository-local files |
| `inputs` | No, defaults to `[]` | array | Typed input contract |
| `outputs` | No, defaults to `[]` | array | Typed output contract |
| `parameter_groups` | No, defaults to `[]` | array | Grouped typed parameters |
| `execution` | Yes for new manifests | object | Execution profiles |
| `compatibility` | No, defaults by source type | object | Playground and compatibility metadata |
| `install` | Recommended for installable components | object | Local install strategies and local smoke test |
| `hpc` | Required for HPC smoke tests | object | HPC install hints and HPC smoke test |
| `ui` | No | object | Playground and Pipeline Constructor presentation metadata |

Unknown top-level fields are currently allowed, but they SHOULD be documented
and namespaced when they are experimental.

## `metadata`

`metadata` identifies the component version.

```yaml
metadata:
  name: gltf_validator
  label: glTF/GLB Validator
  description: Validate glTF and GLB assets before publication.
  tags: [3d, gltf, validation]
  keywords: [gltf validation, 3d model qa]
  category: 3D QA
  version: "1.0.0"
  status: alpha
  component_schema: "0.1.0-alpha.1"
  maintainer: "Example Lab"
  license: MIT
  citation: "Example Lab (2026). glTF/GLB Validator HDP Component."
```

Required fields:

| Field | Type | Rule |
|---|---|---|
| `name` | string | MUST be non-empty; SHOULD be lowercase snake_case and start with a letter |
| `version` | string | MUST be non-empty; SHOULD be semantic-version-like, for example `1.0.0` |

Recommended fields:

| Field | Type | Meaning |
|---|---|---|
| `label` | string | Human-facing component name |
| `description` | string | Short explanation of what the component does |
| `tags` | array of strings | Search/filter tags |
| `keywords` | array of strings | Additional search terms |
| `category` | string | UI grouping, for example `3D QA` |
| `status` | string | Maturity marker such as `alpha`, `beta`, `stable`, or `deprecated` |
| `component_schema` | string | Manifest contract marker; current examples use `0.1.0-alpha.1` |
| `maintainer` | string | Person, team, or institution responsible for the component |
| `license` | string or object | Reuse license for component code and artifacts |
| `citation` | string or object | Citation or acknowledgement text |

Best practices:

- Treat `metadata.name` as permanent once published.
- Change `metadata.version` whenever behavior, outputs, or defaults change in a
  way that may affect pipelines.
- Keep `description` useful to someone who did not write the component.
- Do not encode install strategy or runtime in `metadata.name`; use profiles
  and `install.strategies` for that.

## `sources`

`sources` records source-code and upstream references. WebHDP does not require
it to run the component, but published components SHOULD provide it.

```yaml
sources:
  git: "https://codeberg.org/example/gltf-validator"
  upstream: "https://github.com/KhronosGroup/glTF-Validator"
  documentation: "https://example.org/docs/gltf-validator"
```

For curated discovery, Git release metadata is stored in the component index.
The manifest MAY still keep human-readable source references.

## `distribution`

`distribution` explains whether the component is bundled with WebHDP or
installed separately.

```yaml
distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope:
    - local_container
    - hpc_sif
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `tier` | string | Recommended value for external components: `external_installable` |
| `bundled_with_webhdp` | boolean | `false` for separately installed components |
| `installation_scope` | array | Supported installer strategies, usually `local_container`, `hpc_sif`, or both |

Best practices:

- External components SHOULD use `tier: external_installable`.
- Core WebHDP internals SHOULD NOT masquerade as installable external
  components.
- If `installation_scope` includes `hpc_sif`, also provide an HPC execution
  profile and `hpc.test` when practical.

## `structure`

`structure` declares repository-local files that must exist for developer
validation. It is mostly useful before publishing.

```yaml
structure:
  required_files:
    - runner.py
    - Dockerfile
```

Rules:

- `structure` MUST be an object when declared.
- `structure.required_files` entries MUST stay inside the component directory.
- Entries MUST NOT reference `component.yaml` itself as an escaped path or
  through traversal.

## Field Definitions

`inputs`, `outputs`, and `parameter_groups[].parameters` use the same field
definition shape.

```yaml
name: input_file
label: Input File
description: Source file to process.
type: file_path
required: true
default: null
options: []
mutex_with: []
```

Common fields:

| Field | Required | Type | Meaning |
|---|---:|---|---|
| `name` | Yes | string | Stable machine identifier |
| `type` | No, defaults to `string` | string | Field type |
| `label` | No | string | Human label; defaults to `name` |
| `description` | No | string | Help text and schema description |
| `required` | No, defaults to `false` | boolean | Whether Playground/API input must provide a value |
| `default` | No | type-dependent | Default value |
| `bind_source_by_default` | No, defaults to `true` | boolean | On a `file_path` or `file_list` input, use pipeline source files for an unbound field. Set to `false` for optional sidecar files or dependency lists that require an explicit binding. |
| `extensions` | No | array of file suffixes | On a `file_path` output, declare the file suffixes the component may produce. WebHDP checks declared suffixes during Docker contract execution and can use them to reject incompatible HMSM artifact bindings. |
| `options` | Required for `string_dropdown` | array | Allowed dropdown choices |
| `mutex_with` | No | array of strings | Mutually exclusive field names |

Field names:

- MUST be non-empty.
- MUST be unique across all `inputs` and parameters.
- Output field names MUST be unique among outputs.
- SHOULD use lowercase snake_case.
- SHOULD remain stable after publication.

## Field Types

Supported field types:

| Type | Runtime Value | Typical Use |
|---|---|---|
| `file_path` | string path | Single staged file |
| `dir_path` | string path | Directory input |
| `file_list` | array of string paths | Multiple staged files |
| `boolean` | boolean | Checkbox/toggle parameter |
| `integer` | integer | Count, threshold, discrete setting |
| `number` | number | Floating-point threshold |
| `string_dropdown` | string | Controlled option set |
| `string` | string | Short text |
| `text` | string | Longer text |
| `json` | object or array | Structured parameter |
| `array[string]` | array of strings | Multi-value string parameter |
| `array[number]` | array of numbers | Multi-value numeric parameter |
| `array[integer]` | array of integers | Multi-value integer parameter |

Aliases accepted during normalization:

| Alias | Normalized Type |
|---|---|
| `file` | `file_path` |
| `directory` | `dir_path` |
| `dropdown` | `string_dropdown` |

Default-value rules:

- `boolean`, `integer`, and `number` defaults are coerced to their declared
  type.
- `file_list` defaults MUST be arrays.
- `array[...]` defaults MUST be arrays.
- `string`, `text`, `file_path`, `dir_path`, and `string_dropdown` defaults
  MUST NOT be objects or arrays.
- `string_dropdown.default`, when non-empty, MUST be one of `options`.

Best practices:

- Prefer `string_dropdown` over free text when values drive branching logic.
- Use `json` only when the structure is genuinely open or nested.
- Keep required fields minimal; required inputs make Playground and pipelines
  stricter.

## `inputs`

`inputs` define files, directories, or values supplied to the component.

```yaml
inputs:
  - name: input_file
    label: Input 3D Asset
    description: Source .glb, .gltf, .obj, .ply, .las, .laz, or .e57 file.
    type: file_path
    required: true
```

Best practices:

- Use `file_path` for the common "one source file" case.
- Use `file_list` only when the component naturally consumes multiple files.
- Use `dir_path` for directory-oriented tools, but ensure batch workflows can
  resolve the directory unambiguously.
- Make input names semantic: `input_file`, `source_model`, `texture_directory`.

## `outputs`

`outputs` define named results that WebHDP can bind in pipelines and display in
Playground.

```yaml
outputs:
  - name: validation_report
    label: Validation Report
    description: JSON report with file facts, errors, and warnings.
    type: file_path
    extensions: [.json]
    required: false
```

For the WebHDP Docker file contract, a required `file_path` output must point to
a real file under `/outputs`. When `extensions` is declared, WebHDP checks the
suffix of each returned file, including optional outputs. A container success
response fails the run or smoke test if these checks fail.

Best practices:

- Use stable output names; pipeline bindings depend on them.
- Prefer one output per logical artifact.
- Use `default` only when a deterministic output path is meaningful.
- Keep output descriptions concrete enough for pipeline authors.

## `parameter_groups`

`parameter_groups` organize parameters for Playground and Pipeline Constructor.

```yaml
parameter_groups:
  - title: Validation
    description: Configure validation strictness.
    parameters:
      - name: strict
        label: Strict Mode
        type: boolean
        default: false
      - name: max_file_size_mb
        label: Max File Size Warning
        type: integer
        default: 512
```

Rules:

- Each group MUST be an object.
- `title` defaults to `Parameters` when missing.
- `description` defaults to an empty string.
- Parameters use the common field definition shape.
- Parameter names share the same namespace as input names.

Best practices:

- Group parameters by workflow concept, not by implementation module.
- Give every parameter a safe default when possible.
- Avoid adding parameters for internal implementation details.

## `execution`

`execution` declares one or more execution profiles. New manifests MUST declare
it explicitly.

```yaml
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: webhdp-gltf-validator:local
      entrypoint: [python, /app/validator.py]
```

`execution.profiles` MUST be a non-empty array.

Common profile fields:

| Field | Required | Type | Meaning |
|---|---:|---|---|
| `id` | Yes | string | Stable profile identifier |
| `adapter` | Yes | enum | Execution adapter |
| `entrypoint` | Adapter-dependent | array of strings | Command and arguments inside the runtime |
| `working_directory` | No | string | Working directory for local CLI/legacy profiles |
| `runtime` | Adapter-dependent | string | Runtime such as `docker` or `singularity` |
| `image` | Adapter-dependent | string | Docker image or installed SIF path |
| `handler` | Adapter-dependent | string | Adapter handler name |
| `environment` | No | object | Environment variables |
| `resources` | No | object | Resource hints |
| `input_bindings` | No | array | Advanced adapter input binding metadata |
| `output_collection` | No | array | Advanced adapter output collection metadata |
| `config` | No | object | Adapter-specific configuration |

Supported adapter values:

| Adapter | Purpose |
|---|---|
| `container_cli` | Run a Docker-backed component through the local container adapter |
| `hpc_link` | Run a SIF-backed component through HPC-Link |
| `local_cli` | Run a local command on the WebHDP host; mainly for trusted internal/dev use |
| `legacy_hdp_python` | Legacy local Python component adapter |
| `builtin_webhdp` | Built-in WebHDP handler |

## `container_cli` Profiles

Use `container_cli` for installable local Docker components.

```yaml
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: ghcr.io/example/component:1.0.0
      entrypoint:
        - python
        - /app/runner.py
      resources:
        gpu_count: 0
        cpus: 1
        memory_mb: 1024
```

Rules:

- `runtime` MUST be `docker` for installable local-container profiles.
- `image` MUST be non-empty.
- `entrypoint` MUST be a non-empty array of non-empty strings.
- `resources.gpu_count`, `resources.cpus`, and `resources.memory_mb`, when
  declared, MUST be non-negative integers.

Best practices:

- Use immutable image digests in published index entries.
- Keep the manifest image human-readable during development if needed, but pin
  production installs through the component index.
- Do not enable local Docker installs on public VPS deployments unless Docker
  access is explicitly part of the security design.

## `hpc_link` Profiles

Use `hpc_link` for installable Singularity/Apptainer SIF components.

```yaml
execution:
  profiles:
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      image: ""
      entrypoint:
        - python
        - /app/runner.py
      resources:
        gpu_count: 0
        cpus: 1
        memory_mb: 2048
```

Rules for the installer-supported generic SIF handler:

- `adapter` MUST be `hpc_link`.
- `handler` MUST be `generic_singularity_component`.
- `runtime` MUST be `singularity`.
- `entrypoint` MUST be a non-empty array of non-empty strings.
- `image` MAY be empty in the source manifest. The installer writes the
  installed remote SIF path into the registered profile.

Best practices:

- Keep the local Docker and HPC SIF profiles semantically equivalent when they
  share the same component version.
- Record the SIF SHA-256 in the component index or install payload.
- Keep HPC smoke-test fixtures tiny.

## `local_cli`, `legacy_hdp_python`, And `builtin_webhdp`

These adapters exist for internal and legacy use.

`local_cli` and `legacy_hdp_python` profiles require an `entrypoint`. For local
Python scripts, validator checks ensure relative `.py` entrypoints stay inside
the component directory.

`builtin_webhdp` profiles require a `handler` and are intended for WebHDP-owned
runtime behavior, not separately published external components.

External component developers SHOULD prefer `container_cli` or `hpc_link`.

## `compatibility`

`compatibility` records WebHDP feature compatibility.

```yaml
compatibility:
  playground:
    enabled: true
```

`compatibility.playground` may be:

- an object with `enabled` and optional `reason`
- a boolean

When omitted:

- external/local-catalog components default to Playground enabled
- built-in components default according to WebHDP source type behavior

Examples:

```yaml
compatibility:
  playground:
    enabled: false
    reason: Requires batch pipeline context and is not meaningful as a standalone Playground run.
```

The component index, not the manifest, carries install-time WebHDP version
range fields such as `webhdp_min` and `webhdp_max`.

## `install`

`install` declares WebHDP installer strategies and the local Docker smoke test.

```yaml
install:
  strategies:
    - id: local_container
      runtime: docker
      profile: local_docker
      image: ghcr.io/example/component:1.0.0
    - id: hpc_sif
      runtime: singularity
      profile: hpc_singularity
  test:
    files:
      - name: sample.glb
        content_base64: "..."
    inputs:
      input_file: sample.glb
    parameters:
      strict: false
```

`install.strategies` entries:

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | `local_container` or `hpc_sif` |
| `runtime` | Recommended | `docker` for local, `singularity` for HPC |
| `profile` | Recommended | Existing `execution.profiles[].id` |
| `image` | Required for `local_container` | Docker image reference |

Rules:

- `install` MUST be an object when declared.
- `install.strategies` MUST be an array when declared.
- Strategy IDs MUST be unique.
- Strategy IDs MUST be `local_container` or `hpc_sif`.
- `profile`, when declared, MUST reference an existing execution profile.
- `local_container` strategies MUST declare `image`.

## Smoke-Test Metadata

Smoke tests use the same object shape under `install.test` and `hpc.test`.

```yaml
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
  timeout_seconds: 300
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `files` | array | Small fixture files written before the run |
| `inputs` | object | Request input values |
| `parameters` | object | Request parameter values |
| `timeout_seconds` | number | Optional test timeout |

`files` entries:

| Field | Required | Meaning |
|---|---:|---|
| `name` | Yes | Simple file name, no slash, no traversal |
| `content` | One of `content` or `content_base64` | Text fixture content |
| `content_base64` | One of `content` or `content_base64` | Binary fixture content |

Best practices:

- Keep smoke-test fixtures tiny.
- Use `content_base64` for binary fixtures.
- Reference declared fixture names from `inputs`.
- Do not use smoke tests as performance benchmarks.

## `hpc`

`hpc` contains HPC-specific install hints and the HPC smoke test.

```yaml
hpc:
  install:
    runtime: singularity
    sif_required: true
  test:
    files:
      - name: sample.glb
        content_base64: "..."
    inputs:
      input_file: sample.glb
    parameters: {}
```

Rules:

- `hpc` MUST be an object when declared.
- `hpc.install` MUST be an object when declared.
- `hpc.install.runtime`, when declared, MUST be `singularity`.
- If `hpc.install.sif_required` is true, a missing `hpc.test` produces a
  validator warning.

## `ui`

`ui` controls how fields and results appear in Playground and Pipeline
Constructor. It does not change the runtime contract.

```yaml
ui:
  playground:
    fields:
      input_file:
        widget: model_input
        accept_extensions: [.glb, .gltf]
        help_text: Select a staged glTF or GLB file.
      strict:
        widget: checkbox
    result:
      artifact_views:
        - id: validation-report
          label: Validation Report
          widget: file_download
          extensions: [.json]
      show_result_json: true
      show_logs: true
```

Rules:

- `ui` MUST be an object when declared.
- `ui.playground` MUST be an object when declared.
- `ui.playground.fields` MUST be an object whose keys reference known input or
  parameter names.
- `ui.playground.result` MUST be an object when declared.
- `ui.constructor` MUST be an object when declared.

## Playground Field UI

Supported `ui.playground.fields.<field>.widget` values:

| Widget | Typical Field Types |
|---|---|
| `text_input` | `string` |
| `textarea` | `text` |
| `number_input` | `integer`, `number` |
| `checkbox` | `boolean` |
| `select` | `string_dropdown` |
| `json_editor` | `json` |
| `file_picker` | `file_path` |
| `directory_picker` | `dir_path` |
| `file_list_picker` | `file_list` |
| `array_editor` | `array[...]` |
| `image_input` | image `file_path` |
| `model_input` | 3D model `file_path` |

Additional UI fields:

| Field | Type | Meaning |
|---|---|---|
| `placeholder` | string | Placeholder text |
| `help_text` | string | Short help text |
| `rows` | positive integer | Textarea/editor row hint |
| `path_source` | string | File browser source hint, usually `files` or `directories` |
| `preview_kind` | string | Preview hint, usually `image` or `model` |
| `accept_extensions` | array | Allowed extensions, normalized with leading dots |
| `accept_mime_types` | array | Allowed MIME types |
| `mutex_with` | array | Mutually exclusive field names |
| `visible_if` | object | Conditional visibility rule |

`visible_if` examples:

```yaml
visible_if:
  field: output_format
  equals: glb
```

```yaml
visible_if:
  field: repair_mode
  in: [safe, aggressive]
```

Supported `visible_if` comparison keys:

- `equals`
- `not_equals`
- `truthy`
- `in`

`visible_if.field` MUST reference a known input or parameter.

## Playground Result UI

`ui.playground.result.artifact_views` controls artifact presentation.

```yaml
ui:
  playground:
    result:
      artifact_views:
        - id: images
          label: Image Outputs
          widget: image_gallery
          extensions: [.png, .jpg, .jpeg]
        - id: models
          label: 3D Outputs
          widget: model_viewer
          extensions: [.glb, .gltf, .usdz]
        - id: reports
          label: Reports
          widget: file_download
          extensions: [.json, .txt]
      show_result_json: true
      show_logs: true
```

Supported artifact view widgets:

- `image_gallery`
- `model_viewer`
- `file_download`

If `artifact_views` is omitted, WebHDP uses default image, 3D model, and
structured-data views.

## Constructor UI

`ui.constructor.outputs` adds Pipeline Constructor hints for output-derived
trigger fields and selector examples.

```yaml
ui:
  constructor:
    outputs:
      validation_report:
        trigger_fields:
          - path: "$.validation.error_count"
            label: Error Count
            value_type: integer
            operators: [eq, gte, lte]
          - path: "$.validation.status"
            label: Validation Status
            value_type: string
            operators: [eq, neq, in]
            options:
              - valid
              - warning
              - failed
        selector_examples:
          - "$.validation.status"
          - "$.facts.width"
```

Rules:

- Output names under `ui.constructor.outputs` MUST reference declared outputs.
- Trigger field paths MUST start with `$.`.
- Trigger operators MUST be one of:
  `eq`, `neq`, `in`, `not_in`, `gte`, `lte`, `between`, `exists`, `truthy`.

## Runtime Request Contract

When WebHDP runs a component, it provides environment variables:

| Variable | Meaning |
|---|---|
| `WEBHDP_COMPONENT_REQUEST` | Path to request JSON |
| `WEBHDP_COMPONENT_RESPONSE` | Path where response JSON should be written |
| `WEBHDP_INPUT_DIR` | Mounted input directory |
| `WEBHDP_OUTPUT_DIR` | Output directory for generated files |
| `WEBHDP_COMPONENT_KEY` | Component key |

Typical request:

```json
{
  "component_key": "image_inspector",
  "version": "1.0.0",
  "inputs": {
    "input_file": "sample.ppm"
  },
  "parameters": {},
  "metadata": {
    "install_strategy": "local_container"
  }
}
```

The manifest defines the shape of `inputs` and `parameters`; the runner reads
the request and resolves staged files under `WEBHDP_INPUT_DIR`.

## Runtime Response Contract

The component SHOULD write a response JSON file to
`WEBHDP_COMPONENT_RESPONSE` and MAY also print the same JSON to stdout.

Successful response:

```json
{
  "success": true,
  "status": "completed",
  "error": null,
  "outputs": {
    "image_report": "/outputs/sample_image_report.json"
  },
  "artifacts": [
    {
      "artifact_kind": "file",
      "name": "sample_image_report.json",
      "remote_path": "/outputs/sample_image_report.json",
      "metadata": {
        "component": "image_inspector",
        "role": "image_report"
      }
    }
  ],
  "facts": {
    "width": 1,
    "height": 1
  },
  "logs": {
    "stdout": "Inspected sample.ppm",
    "stderr": ""
  }
}
```

Failure response:

```json
{
  "success": false,
  "status": "failed",
  "error": "input_file is required",
  "outputs": {},
  "artifacts": [],
  "logs": {
    "stdout": "",
    "stderr": "input_file is required"
  }
}
```

Best practices:

- Always write a response on expected failures.
- Write generated files under `WEBHDP_OUTPUT_DIR`.
- Keep `outputs` aligned with manifest output names.
- Include enough logs and facts for troubleshooting and provenance.
- Do not write outside mounted input/output/request/response locations.

## Validation And Normalization

WebHDP normalizes manifests before storing or using them.

Normalization behavior:

- Missing `inputs`, `outputs`, and `parameter_groups` become empty arrays.
- Missing `compatibility` becomes an object with normalized Playground
  compatibility.
- Field type aliases are normalized.
- Labels default to field names.
- Descriptions default to empty strings.
- Field defaults are coerced according to field type.
- Playground and Constructor schemas are generated from the manifest.
- Unknown fields are preserved by the Pydantic model for forward compatibility.

Developer validation command:

```bash
uv run python scripts/validate_hdp_components.py external_code/<component_name>
```

Strict validation:

```bash
uv run python scripts/validate_hdp_components.py external_code/<component_name> --strict-warnings
```

All local components:

```bash
make hdp-components-check
```

## Manifest Versus Component Index

The manifest and component index are different artifacts.

| Artifact | Defines | Example |
|---|---|---|
| Component manifest | Runtime contract for one component version | `external_code/gltf_validator/component.yaml` |
| Component index | Curated discovery metadata and artifact provenance | `docs/examples/component-index/index.json` |

The manifest SHOULD NOT carry all publication metadata. The component index is
where WebHDP stores:

- manifest URL and SHA-256
- Git URL, tag, and commit
- release URL, tag, and assets
- Zenodo DOI and concept DOI
- trust level
- WebHDP version compatibility range
- Docker digest
- SIF source and SHA-256
- SBOM and provenance URLs

See `hdp_component_publishing_guide.md` for the publication workflow.

## Complete Dual-Strategy Example

```yaml
metadata:
  name: gltf_validator
  label: glTF/GLB Validator
  description: Validate glTF and GLB assets before publication or conversion.
  tags: [3d, gltf, glb, validation]
  keywords: [gltf validation, glb validation, 3d model qa]
  category: 3D QA
  version: "1.0.0"
  status: alpha
  component_schema: "0.1.0-alpha.1"

sources:
  git: "https://github.com/hdp-components/gltf_validator"

distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope:
    - local_container
    - hpc_sif

inputs:
  - name: input_file
    label: Input glTF/GLB
    description: Source .gltf or .glb file to validate.
    type: file_path
    required: true

outputs:
  - name: validation_report
    label: Validation Report
    description: JSON report with file facts, errors, and warnings.
    type: file_path

parameter_groups:
  - title: Validation
    description: Configure validation strictness.
    parameters:
      - name: strict
        label: Strict Mode
        type: boolean
        default: false
      - name: max_file_size_mb
        label: Max File Size Warning
        type: integer
        default: 512

execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: webhdp-gltf-validator:local
      entrypoint: [python, /app/validator.py]
      resources:
        gpu_count: 0
        cpus: 1
        memory_mb: 2048
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      image: ""
      entrypoint: [python, /app/validator.py]
      resources:
        gpu_count: 0
        cpus: 1
        memory_mb: 2048

compatibility:
  playground:
    enabled: true

install:
  strategies:
    - id: local_container
      runtime: docker
      profile: local_docker
      image: webhdp-gltf-validator:local
    - id: hpc_sif
      runtime: singularity
      profile: hpc_singularity
  test:
    files:
      - name: sample.glb
        content_base64: "Z2xURgIAAAAwAAAAHAAAAEpTT057ImFzc2V0Ijp7InZlcnNpb24iOiIyLjAifX0g"
    inputs:
      input_file: sample.glb
    parameters:
      strict: false
      max_file_size_mb: 512

ui:
  playground:
    fields:
      input_file:
        widget: model_input
        accept_extensions: [.glb, .gltf]
        help_text: Select a staged glTF or GLB file.
      strict:
        widget: checkbox
      max_file_size_mb:
        widget: number_input
    result:
      artifact_views:
        - id: validation-report
          label: Validation Report
          widget: file_download
          extensions: [.json]
      show_result_json: true
      show_logs: true

hpc:
  install:
    runtime: singularity
    sif_required: true
  test:
    files:
      - name: sample.glb
        content_base64: "Z2xURgIAAAAwAAAAHAAAAEpTT057ImFzc2V0Ijp7InZlcnNpb24iOiIyLjAifX0g"
    inputs:
      input_file: sample.glb
    parameters:
      strict: false
      max_file_size_mb: 512
```

## Best-Practice Checklist

Before publishing or handing a manifest to an administrator:

- `metadata.name` is lowercase snake_case and stable.
- `metadata.version` is semantic-version-like and has not been reused.
- `metadata.description` explains the component's purpose.
- `distribution.tier` is `external_installable` for separately installed
  components.
- Inputs, outputs, and parameters are typed and documented.
- Output names are stable and meaningful.
- Execution profile IDs are unique.
- Local Docker profiles declare `adapter: container_cli`, `runtime: docker`,
  image, and entrypoint.
- HPC profiles declare `adapter: hpc_link`,
  `handler: generic_singularity_component`, `runtime: singularity`, and
  entrypoint.
- `install.strategies` references real profile IDs.
- `install.test` exists for local Docker components.
- `hpc.test` exists for HPC SIF components when practical.
- UI field references point to real inputs or parameters.
- Smoke-test fixture files are small and self-contained.
- `make hdp-components-check` passes.
- The component runner writes response JSON on success and expected failures.

## Related References

- `docs/development/first_hdp_component.md`
- `docs/development/hdp_component_publishing_guide.md`
- `docs/guides/hdp_component_hpc_installation.md`
- `docs/schemas/webhdp_component_manifest_v0_1_0_alpha_1.schema.json`
- `docs/schemas/webhdp_component_index_v1.schema.json`
- `external_code/gltf_validator/component.yaml`
- `scripts/validate_hdp_components.py`
- `services/native_pipeline_system.py`
- `schemas/native_pipeline_schemas.py`
