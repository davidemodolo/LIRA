# L.I.R.A. Dockerfile
# Multi-stage build for optimal image size

# ==============================================================================
# Stage 1: Builder
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./

RUN uv sync --frozen --no-dev

COPY src/ ./src/

# ==============================================================================
# Stage 2: Development
# ==============================================================================
FROM builder AS development

RUN uv sync --frozen --extra dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

CMD ["uv", "run", "lira"]

# ==============================================================================
# Stage 3: Runtime
# ==============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd --gid 1000 lira \
    && useradd --uid 1000 --gid lira --shell /bin/bash lira

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_ENV=production

USER lira

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD uv run python -c "import lira; print('ok')" || exit 1

CMD ["uv", "run", "uvicorn", "lira.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
