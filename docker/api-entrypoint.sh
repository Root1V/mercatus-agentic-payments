#!/usr/bin/env sh
set -e

echo "[api-entrypoint] aplicando migraciones..."
alembic upgrade head

echo "[api-entrypoint] sembrando catálogo (si está vacío)..."
agent-commerce catalog seed

echo "[api-entrypoint] arrancando uvicorn..."
exec uvicorn agent_commerce.dashboard.app:build_dashboard_app --factory --host 0.0.0.0 --port 8000
