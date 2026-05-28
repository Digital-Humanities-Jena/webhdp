# Build Your First HDP Component

This guide shows how to turn an ordinary container into an HDP Component that
WebHDP can validate, install, run in Playground, and reuse in pipelines.

Use this guide when you are a new WebHDP developer and you want the shortest
clear path from "I have a container" to "WebHDP can run it as a component."

## The Core Idea

An HDP Component is not a Flask route, a Vue component, or code imported into
WebHDP. It is a separate executable package with a manifest and a small runtime
contract.

WebHDP owns:

- component registration
- input staging
- execution profile selection
- run state
- artifact collection
- provenance-friendly result storage
- Playground and pipeline orchestration

Your component owns:

- the container image
- the runner entrypoint
- the domain-specific processing logic
- the structured result it returns

In practice, almost any container can become an HDP Component if it can:

1. read a JSON request file
2. read staged input files
3. write outputs into the output directory
4. write a JSON response file
5. exit with `0` for success or non-zero for failure

## Example: Image Inspector

The example component inspects an image and writes a JSON report with basic
facts such as format, width, height, and color mode.

This is intentionally small. The same pattern works for larger containers that
wrap GDAL, ExifTool, Blender, OCR engines, ML models, validators, or legacy
command-line tools.

Recommended package shape:

```text
external_code/
  image_inspector/
    component.yaml
    runner.py
    Dockerfile
```

## 1. Write The Manifest

Create `external_code/image_inspector/component.yaml`:

```yaml
metadata:
  name: image_inspector
  label: Image Inspector
  description: Extracts basic image facts for cultural heritage image files.
  tags: [image, qa, metadata]
  category: Image QA
  version: "1.0.0"
  status: alpha
  component_schema: "0.1.0-alpha.1"

distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope: [local_container]

inputs:
  - name: input_file
    label: Input Image
    description: Source image to inspect.
    type: file_path
    required: true

outputs:
  - name: image_report
    label: Image Report
    description: JSON report with detected image facts.
    type: file_path
    required: false

execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: webhdp-image-inspector:local
      entrypoint: [python, /app/runner.py]
      resources:
        gpu_count: 0
        cpus: 1
        memory_mb: 512

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

ui:
  playground:
    fields:
      input_file:
        widget: file_input
        accept_extensions: [.jpg, .jpeg, .png, .tif, .tiff, .ppm]
        help_text: Select a staged image file.
    result:
      artifact_views:
        - id: image-report
          label: Image Report
          widget: file_download
          extensions: [.json]
      show_result_json: true
      show_logs: true
```

Important fields:

- `metadata.name` is the stable component identifier. Keep it lowercase and
  machine-friendly.
- `metadata.version` identifies the executable contract. Change it when
  behavior or outputs change.
- `distribution.tier: external_installable` tells WebHDP this is a separately
  installed component package.
- `inputs` and `outputs` define the typed contract visible to Playground and
  pipelines.
- `execution.profiles` tells WebHDP how to run the component.
- `install.test` gives administrators and CI a tiny smoke test.
- `ui.playground` makes the component pleasant to test interactively.

The smoke test uses a tiny text-based PPM image so the manifest can stay
self-contained. For binary fixtures, use `content_base64` instead of `content`.

## 2. Write The Runner

Create `external_code/image_inspector/runner.py`:

```python
#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image


def read_request() -> dict[str, Any]:
    request_path = os.environ.get("WEBHDP_COMPONENT_REQUEST")
    if not request_path:
        raise RuntimeError("WEBHDP_COMPONENT_REQUEST is not set")

    with open(request_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise RuntimeError("Component request must be a JSON object")
    return payload


def write_response(payload: dict[str, Any]) -> None:
    response_path = os.environ.get("WEBHDP_COMPONENT_RESPONSE")
    if response_path:
        target = Path(response_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(payload, sort_keys=True))


def input_root() -> Path:
    return Path(os.environ.get("WEBHDP_INPUT_DIR") or "/inputs")


def output_root() -> Path:
    root = Path(os.environ.get("WEBHDP_OUTPUT_DIR") or "/outputs")
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_input(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("input_file is required")

    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    for option in (input_root() / text, input_root() / candidate.name):
        if option.exists():
            return option.resolve()

    raise FileNotFoundError(f"Could not resolve input_file {text!r}")


def main() -> int:
    started = time.time()
    request = read_request()
    inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
    input_path = resolve_input(inputs.get("input_file"))

    output_dir = output_root()
    report_path = output_dir / f"{input_path.stem}_image_report.json"

    with Image.open(input_path) as image:
        report = {
            "file_name": input_path.name,
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "duration_seconds": time.time() - started,
        }

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    response = {
        "success": True,
        "status": "completed",
        "error": None,
        "outputs": {
            "image_report": str(report_path),
        },
        "artifacts": [
            {
                "artifact_kind": "file",
                "name": report_path.name,
                "remote_path": str(report_path),
                "metadata": {
                    "component": "image_inspector",
                    "role": "image_report",
                },
            }
        ],
        "facts": report,
        "logs": {
            "stdout": f"Inspected {input_path.name}",
            "stderr": "",
        },
    }
    write_response(response)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        write_response(
            {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "logs": {
                    "stdout": "",
                    "stderr": str(exc),
                },
            }
        )
        raise SystemExit(1)
```

The runner is the adapter between WebHDP and your container. It can call a
library directly, shell out to a CLI, run a model, or invoke existing scripts.
The only WebHDP-specific part is the request/response contract.

## 3. Write The Dockerfile

Create `external_code/image_inspector/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir pillow

COPY runner.py /app/runner.py
```

Build the local image:

```bash
docker build -t webhdp-image-inspector:local external_code/image_inspector
```

WebHDP does not build Docker images during component installation. Build or pull
the image first on the machine that runs the WebHDP backend or worker.

## 4. Understand The Runtime Contract

When WebHDP runs the component, it prepares environment variables for the
container:

| Variable | Meaning |
|---|---|
| `WEBHDP_COMPONENT_REQUEST` | Path to the JSON request file |
| `WEBHDP_COMPONENT_RESPONSE` | Path where the component should write its JSON response |
| `WEBHDP_INPUT_DIR` | Directory containing staged input files |
| `WEBHDP_OUTPUT_DIR` | Directory where generated outputs should be written |

The request contains at least:

```json
{
  "inputs": {
    "input_file": "sample.ppm"
  },
  "parameters": {},
  "metadata": {}
}
```

The response should include:

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
        "component": "image_inspector"
      }
    }
  ],
  "logs": {
    "stdout": "Inspected sample.ppm",
    "stderr": ""
  }
}
```

Clarifications:

- `outputs` maps declared output names to generated file paths.
- `artifacts` tells WebHDP which files should be exposed to users or preserved
  with run results.
- `facts`, `validation`, `qa`, or other structured sections may be added when
  useful. Keep them stable once pipelines depend on them.
- A failed component should still write a response when possible. This gives
  users and operators a useful error instead of a silent container failure.

## 5. Validate The Component

Run the manifest validator from the repository root:

```bash
uv run python scripts/validate_hdp_components.py external_code/image_inspector
```

For all component manifests:

```bash
make hdp-components-check
```

For documentation and catalog links after adding this guide or related docs:

```bash
make docs-check
```

Validation should happen before installation. It catches malformed manifests,
missing entrypoints, invalid profile shapes, and broken smoke-test metadata.

## 6. Install And Try It In WebHDP

For local Docker-backed components, the deployment must intentionally allow
local component execution. A typical local development configuration uses:

```bash
WEBHDP_DEPLOYMENT_MODE=local
WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true
WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST=webhdp-image-inspector:local
```

Then use the in-app installer:

1. Open Tools -> HDP Component Installer.
2. Select or provide the `image_inspector` package.
3. Choose the `local_container` strategy.
4. Validate the manifest and image policy.
5. Install the component.
6. Run the declared smoke test.
7. Open Playground and run the component against a staged image.

If the component is visible in Playground and the smoke test succeeds, the
basic component integration is working.

## 7. Adapt The Pattern To Any Container

Most existing containers already do useful work through a command like:

```bash
some-tool --input /inputs/source.tif --output /outputs/report.json
```

To turn that into an HDP Component, keep the tool unchanged and write a small
runner that:

1. reads `WEBHDP_COMPONENT_REQUEST`
2. resolves WebHDP input names to real paths under `WEBHDP_INPUT_DIR`
3. calls the existing tool with those paths
4. writes generated files under `WEBHDP_OUTPUT_DIR`
5. maps tool outputs into WebHDP's `outputs` and `artifacts`
6. returns a structured success or failure response

The runner should be thin. Avoid reimplementing the domain tool inside WebHDP.
The point of the component model is to keep specialized processing portable,
installable, and reproducible outside the core application.

## 8. When To Add Parameters

Add parameters when a user or pipeline author needs controlled variation:

```yaml
parameter_groups:
  - title: Inspection
    parameters:
      - name: fail_on_large_image
        label: Fail On Large Image
        type: boolean
        default: false
      - name: max_megapixels
        label: Max Megapixels
        type: integer
        default: 100
```

Then read them from `request["parameters"]` in the runner.

Keep parameters explicit and typed. A small set of clear options is easier to
use in Playground, safer in pipelines, and easier to preserve in provenance.

## 9. Local Docker vs HPC SIF

This guide uses `local_container` because it is the simplest developer path.
For larger jobs, institutional deployments, or stricter runtime isolation, the
same component can also declare an `hpc_sif` strategy with a Singularity
execution profile.

Use the installation guide for strategy details:

- local Docker image policy and allowlists
- HPC-Link/Singularity installation
- digest and checksum recording
- local and HPC profiles for the same component version

Reference: `docs/guides/hdp_component_hpc_installation.md`.

## 10. Developer Checklist

Before handing a component to an administrator or pipeline author, confirm:

- `component.yaml` has stable metadata, typed inputs, typed outputs, execution
  profiles, install strategy, and smoke test.
- The runner reads `WEBHDP_COMPONENT_REQUEST`.
- The runner writes files only under `WEBHDP_OUTPUT_DIR`.
- The runner writes `WEBHDP_COMPONENT_RESPONSE` on success and on expected
  failure paths.
- The Docker image or SIF artifact exists outside WebHDP.
- `uv run python scripts/validate_hdp_components.py external_code/<name>`
  succeeds.
- The install smoke test uses a tiny fixture and realistic inputs.
- The component records enough facts, logs, and artifact metadata for a future
  user to understand what happened.

## Related References

- `docs/development/hdp_component_manifest_specification.md`
- `docs/development/hdp_component_publishing_guide.md`
- `docs/architecture/pipeline_platform_contract.md`
- `docs/workflows/3d-hdp-component-lifecycle.md`
- `docs/guides/hdp_component_hpc_installation.md`
- `external_code/gltf_validator/component.yaml`
- `external_code/gltf_validator/validator.py`
