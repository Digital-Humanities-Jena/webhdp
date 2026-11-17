FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
LABEL org.opencontainers.image.title="WebHDP Zenodo community component adapters" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends blender ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Blender uses Debian's Python 3.11, separately from the Python 3.12 CLI.
# Its glTF exporter must have NumPy in that interpreter as well.
RUN apt-get update && apt-get install -y --no-install-recommends python3-numpy && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN blender --background --factory-startup --python-exit-code 1 --python-expr 'import bpy, numpy, os; bpy.ops.export_scene.gltf(filepath="/tmp/runtime-smoke.glb", export_format="GLB"); assert open("/tmp/runtime-smoke.glb", "rb").read(4) == b"glTF"; os.remove("/tmp/runtime-smoke.glb")' && python -c 'import PIL, numpy, trimesh, pygltflib, ftfy, pypdf, mutagen'
CMD ["python", "/app/component_runner.py", "--help"]
