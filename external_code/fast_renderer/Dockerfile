FROM python:3.11-slim

ARG TARGETARCH
ARG APT_RETRIES=5

# Install system dependencies for Blender and general utils
# Added 'curl' for healthchecks if needed, and 'xz-utils' for extraction
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    for attempt in 1 2 3; do \
        apt-get update -o Acquire::Retries="${APT_RETRIES}" && \
        apt-get install -y --fix-missing \
            wget \
            curl \
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
            python3-numpy && \
        rm -rf /var/lib/apt/lists/* && \
        break; \
        if [ "${attempt}" -eq 3 ]; then exit 1; fi; \
        echo "APT dependency install failed (attempt ${attempt}), retrying..." >&2; \
        sleep $((attempt * 5)); \
    done

WORKDIR /opt

# Architecture-specific Blender Installation
# For ARM64 (M1/M2/M3), we use the Debian package (Blender 3.4+) for native speed.
# For AMD64, we download the official Blender 3.6.5 LTS tarball for consistency.
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
    fi

# Setup Application
WORKDIR /app
COPY requirements.txt .
# Install Flask for the API wrapper (not in requirements.txt usually)
RUN pip install flask gunicorn

COPY . .

# Environment variables
ENV PORT=5002
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 5002

# Start the API server
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "1", "--threads", "4", "--timeout", "1200", "server:app"]
