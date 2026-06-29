# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder: resolve and install dependencies into a self-contained virtualenv.
# uv lives only in this stage, so it never ships in the runtime image.
# ---------------------------------------------------------------------------
# Base pinned by digest for reproducible builds (the tag alone is mutable).
# Refresh deliberately during dependency updates with:
#   docker buildx imagetools inspect python:3.14-slim
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder

# uv pinned to an exact version (never :latest) for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies only (the project is virtual: no build-system, so
# there is nothing to "install" for the app itself). Bind-mounting the lock
# files instead of COPYing them keeps them out of the layer, and the uv cache
# mount makes rebuilds fast. This layer is reused unless uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev

# ---------------------------------------------------------------------------
# Runtime: minimal image with just the venv + app source, running as non-root.
# ---------------------------------------------------------------------------
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

LABEL org.opencontainers.image.title="link-shortener" \
      org.opencontainers.image.description="Minimal self-hosted URL shortener" \
      org.opencontainers.image.source="https://github.com/EuanKerr/link-shortener" \
      org.opencontainers.image.licenses="MIT"

# Run the venv's interpreter directly (uvicorn is on PATH); make the app
# package importable; never buffer or write .pyc so the root FS can stay
# read-only at runtime.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dedicated unprivileged account with a fixed UID/GID.
RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home-dir /app --no-create-home app

WORKDIR /app

# Copy the prebuilt venv (kept at the same path so its scripts stay valid),
# then the application source. --chown avoids a separate chown layer.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app

# Pre-create the data dir owned by the app user. A fresh named volume mounted
# here inherits this ownership, so SQLite can write as non-root. The volume
# itself is declared by docker-compose, not here, to avoid stray anonymous
# volumes on a plain `docker run`.
RUN mkdir -p /data && chown app:app /data

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

# No --proxy-headers: the app never reads the client IP or scheme, and trusting
# X-Forwarded-* (especially with --forwarded-allow-ips "*") would let any peer
# that reaches the socket spoof them. --limit-concurrency caps in-flight
# requests so the blocking-SQLite worker pool can't be swamped into unbounded
# queueing under a flood.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--limit-concurrency", "64"]
