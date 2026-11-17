# Build with --platform linux/amd64: pycolmap 3.13 has no Linux ARM64 wheel.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /app/requirements.txt
COPY component_runner.py upstream.py /app/
RUN python -c 'import pycolmap; import PIL; import numpy; assert hasattr(pycolmap, "FeatureExtractionOptions")'
CMD ["python", "/app/component_runner.py", "--help"]
