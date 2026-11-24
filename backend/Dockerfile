# ---------- Stage 1: install Python packages into a virtual env ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only requirements first so this layer is cached until they change
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------- Stage 2: small runtime image (no pip cache, no build files) ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATABASE_URL=sqlite:////data/app.db

# Run as a normal user; /data (the SQLite folder) must be writable by it
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app

USER appuser
EXPOSE 8000

# Render passes the port in $PORT; locally it falls back to 8000.
# "exec" makes uvicorn PID 1 so it gets Ctrl+C / docker stop signals.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
