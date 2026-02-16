# ─── Backend (FastAPI) Dockerfile ───
# Multi-stage build: slim Python + only needed packages
FROM python:3.10-slim AS base

WORKDIR /app

# System dependencies for scipy, scikit-learn, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy application code
COPY backend/ ./backend/
COPY poc/ ./poc/

# Copy config (NO credentials in image)
COPY backend/config.yaml ./backend/config.yaml
# COPY backend/daisoproject-sst.json ./backend/daisoproject-sst.json

# Environment: STT credentials path (runtime secret mount)
# (docker-compose에서 /run/secrets/daisoproject-sst.json 로 마운트됨)
ENV GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/daisoproject-sst.json

# Non-root user for security
RUN useradd --create-home appuser \
 && mkdir -p /app/outputs/normalized \
 && chown -R appuser:appuser /app/outputs
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
