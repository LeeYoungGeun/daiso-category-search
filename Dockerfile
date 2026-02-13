# ─── Backend (FastAPI) Dockerfile ───
# Multi-stage build: slim Python + only needed packages
FROM python:3.10-slim AS base

WORKDIR /app

# System dependencies for scipy, scikit-learn, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy application code
COPY backend/ ./backend/
COPY poc/ ./poc/

# Copy config and credentials
COPY backend/config.yaml ./backend/config.yaml
COPY backend/daisoproject-sst.json ./backend/daisoproject-sst.json

# Environment: STT credentials path (relative, Docker-compatible)
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/backend/daisoproject-sst.json

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# Run with gunicorn for production
CMD ["gunicorn", "backend.main:app", \
    "--worker-class", "uvicorn.workers.UvicornWorker", \
    "--workers", "2", \
    "--bind", "0.0.0.0:8000", \
    "--timeout", "60", \
    "--preload"]
