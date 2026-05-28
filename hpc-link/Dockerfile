FROM python:3.12-slim

WORKDIR /app

# Prevent Python from writing pyc files to disc (read-only container friendly)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for SSH
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
RUN chmod -R a+rX /app/app

# Create .ssh directory for host key caching
RUN mkdir -p /home/appuser/.ssh && chown -R appuser:appuser /home/appuser/.ssh

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
