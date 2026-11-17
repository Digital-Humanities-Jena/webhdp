FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/hmsm-matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-dejavu-core libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY source/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --no-binary=pyvips \
    -r /app/requirements.txt

COPY source/ /app/
COPY component_runner.py hmsm-source.json /app/
RUN HMSM_DATA_DIR=/tmp/hmsm-build-check python -c \
    'from backend.studio import cli, interpretation, reconstruct_cli; from backend.studio.models import get_model; get_model("generic_88")' \
    && rm -rf /tmp/hmsm-build-check /tmp/hmsm-matplotlib

CMD ["python", "/app/component_runner.py", "--help"]
