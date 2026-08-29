# syntax=docker/dockerfile:1

# ---------- etapa 1: build de la UI ----------
FROM node:22-alpine AS ui
WORKDIR /app/ui
COPY ui/package.json ui/pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile
COPY ui/ .
RUN pnpm build

# ---------- etapa 2: python (app) ----------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
COPY --from=ui /app/ui/dist ui/dist
RUN mkdir -p /data

ENV KNW_TOPICS_DIR=/data/topics
ENV KNW_DB_PATH=/data/knw.db
ENV KNW_SESSION_NAME=/data/knw_session

EXPOSE 8000
VOLUME /data
CMD ["uv", "run", "--no-sync", "python", "boot.py"]
