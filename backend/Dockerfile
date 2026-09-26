# backend/Dockerfile

# Stage 1: Builder
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt > requirements.lock \
    && pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.lock

# Stage 2: Final
FROM python:3.11-slim

WORKDIR /app

# Create a non-root user with a real home directory for runtime tooling.
RUN groupadd -r hdpuser && useradd -r -m -d /home/hdpuser -g hdpuser hdpuser

# Install dependencies
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . .

# --- NEW STEPS ---
# Copy entrypoint script and ensure it is executable
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Create directories and set permissions
RUN mkdir -p logs instance && \
    chown -R hdpuser:hdpuser /app

# Switch to non-root user
USER hdpuser

# Environment variables
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Use the entrypoint script to start the container
ENTRYPOINT ["/entrypoint.sh"]
