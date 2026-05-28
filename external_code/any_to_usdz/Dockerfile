FROM python:3.11-slim

ARG TARGETARCH
ARG APT_RETRIES=5

# Install system dependencies for Blender
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    for attempt in 1 2 3; do \
        apt-get update -o Acquire::Retries="${APT_RETRIES}" && \
        apt-get install -y --fix-missing \
            wget \
            curl \
            python3-numpy \
            xz-utils \
            libgl1 \
            libglx-mesa0 \
            libegl1 \
            libdbus-1-3 \
            libxi6 \
            libxrender1 \
            libxrandr2 \
            libxcursor1 \
            libxinerama1 \
            libxkbcommon0 \
            libsm6 \
            libice6 \
            libxxf86vm1 \
            libglib2.0-0 && \
        rm -rf /var/lib/apt/lists/* && \
        break; \
        if [ "${attempt}" -eq 3 ]; then exit 1; fi; \
        echo "APT dependency install failed (attempt ${attempt}), retrying..." >&2; \
        sleep $((attempt * 5)); \
    done

WORKDIR /opt

# Architecture-specific Blender installation. The production Compose files run
# this service as linux/amd64 by default so the official Blender build supplies a
# working USD exporter, including on Apple Silicon through Docker emulation.
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        echo "Detected ARM64 architecture. Installing Blender via APT for native performance..."; \
        export DEBIAN_FRONTEND=noninteractive; \
        for attempt in 1 2 3; do \
            apt-get update -o Acquire::Retries="${APT_RETRIES}" && \
            apt-get install -y --fix-missing blender && \
            rm -rf /var/lib/apt/lists/* && \
            break; \
            if [ "${attempt}" -eq 3 ]; then exit 1; fi; \
            echo "Blender install failed (attempt ${attempt}), retrying..." >&2; \
            sleep $((attempt * 5)); \
        done; \
    else \
        echo "Detected AMD64 architecture. Downloading official Blender 3.6.5..."; \
        BLENDER_URL="https://download.blender.org/release/Blender3.6/blender-3.6.5-linux-x64.tar.xz"; \
        DIR_NAME="blender-3.6.5-linux-x64"; \
        wget "$BLENDER_URL" -O blender.tar.xz; \
        tar -xf blender.tar.xz; \
        mv "$DIR_NAME" blender; \
        rm blender.tar.xz; \
        # Add to PATH manually for the tarball version
        ln -s /opt/blender/blender /usr/local/bin/blender; \
        # Blender tarball ships its own Python, so install NumPy inside that runtime.
        blender --background --python-expr "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'ensurepip', '--upgrade']); subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', 'numpy'])"; \
    fi

RUN blender --background --python-expr "import bpy, os, sys, tempfile; bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.mesh.primitive_cube_add(); output=os.path.join(tempfile.gettempdir(), 'webhdp_usd_export_probe.usdc'); bpy.ops.wm.usd_export(filepath=output); sys.exit(0 if os.path.exists(output) and os.path.getsize(output) > 512 else 1)"

# Setup Application
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Environment variables
ENV PORT=5003
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 5003

# Start the API server
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--workers", "1", "--threads", "4", "--timeout", "1200", "server:app"]
