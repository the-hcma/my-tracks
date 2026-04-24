# syntax=docker/dockerfile:1

# ── Stage 1: Frontend build ─────────────────────────────────────────────────
FROM node:22-slim AS frontend

RUN corepack enable && corepack prepare pnpm@10.28.0 --activate

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY tsconfig.json ./
COPY dev-tooling/esbuild.config.mjs dev-tooling/
COPY web_ui/static/web_ui/ts/ web_ui/static/web_ui/ts/
RUN pnpm run build

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
COPY --from=python-build --chown=app:app /app/app app/
COPY --from=python-build --chown=app:app /app/web_ui web_ui/
COPY --from=python-build --chown=app:app /app/manage.py manage.py
COPY --from=python-build --chown=app:app /app/staticfiles staticfiles/
COPY --from=python-build --chown=app:app /app/scripts/docker-entrypoint docker-entrypoint

RUN mkdir -p /app/logs && chown app:app /app/logs

ARG BUILD_COMMIT=
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    BUILD_COMMIT=${BUILD_COMMIT}

EXPOSE 8080 8883

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health/')"]

USER app

ENTRYPOINT ["./docker-entrypoint"]
CMD ["--log-level", "info"]
