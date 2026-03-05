# syntax=docker/dockerfile:1

# ── Stage 1: Frontend build ─────────────────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY esbuild.config.mjs tsconfig.json ./
COPY web_ui/static/web_ui/ts/ web_ui/static/web_ui/ts/
RUN npm run build

# ── Stage 2: Python build ───────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS python-build

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

COPY . .
COPY --from=frontend /app/web_ui/static/web_ui/js/ web_ui/static/web_ui/js/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen

ENV DJANGO_SETTINGS_MODULE=config.settings
RUN uv run python manage.py collectstatic --noinput --clear

# ── Stage 3: Runtime ────────────────────────────────────────────────────────
FROM python:3.14-slim-bookworm AS runtime

RUN groupadd --system app && useradd --system --gid app --no-create-home app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=python-build --chown=app:app /app/.venv .venv/
COPY --from=python-build --chown=app:app /app/config config/
COPY --from=python-build --chown=app:app /app/my_tracks my_tracks/
COPY --from=python-build --chown=app:app /app/web_ui web_ui/
COPY --from=python-build --chown=app:app /app/manage.py manage.py
COPY --from=python-build --chown=app:app /app/staticfiles staticfiles/
COPY --from=python-build --chown=app:app /app/docker-entrypoint docker-entrypoint

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings

EXPOSE 8080 8883

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health/')"]

USER app

ENTRYPOINT ["./docker-entrypoint"]
CMD ["--log-level", "info"]
