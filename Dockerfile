# Imagen del servicio `api`: el backend del dashboard (FastAPI + Postgres + JWT).
# Multi-stage con uv: la etapa `builder` resuelve dependencias con el lockfile
# (uv.lock, reproducible); la etapa final solo copia el venv ya resuelto y el
# código -- imagen final más chica, sin la caché de resolución de uv.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Cachea la resolución de dependencias por separado del código de la app:
# cambiar código no invalida esta capa.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra dashboard

COPY . .
RUN uv sync --frozen --extra dashboard


FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["/app/docker/api-entrypoint.sh"]
