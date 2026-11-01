#!/usr/bin/env bash
# Levanta o baja todo el stack de Mercatus a demanda.
#
#   scripts/stack.sh up [--sandbox] [--docker]   levanta el stack
#   scripts/stack.sh down                         lo baja (los datos se conservan)
#   scripts/stack.sh status                       qué está corriendo y dónde
#   scripts/stack.sh logs [backend|frontend|docker]  sigue los logs
#
# Modos:
#   (por defecto)  desarrollo: Postgres en Docker; backend y frontend nativos,
#                  con recarga en caliente del frontend (Vite).
#   --docker       todo en contenedores, como en producción (docker-compose.yml).
#   --sandbox      además, el sandbox REAL de Aerarium (banco de AIBank) y el
#                  dashboard conectado a él. Solo en modo desarrollo.
#
# Variables opcionales: STACK_PG_PORT (5433), STACK_API_PORT (8000),
# STACK_WEB_PORT (5173), AERARIUM_DIR (../aerarium-agentic-banking).
#
# El estado (pids, logs y secretos generados) vive en .stack/, ignorado por git.
# Los secretos nunca se imprimen.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/.stack"
PG_PORT="${STACK_PG_PORT:-5433}"
API_PORT="${STACK_API_PORT:-8000}"
WEB_PORT="${STACK_WEB_PORT:-5173}"
AERARIUM_DIR="${AERARIUM_DIR:-$ROOT/../aerarium-agentic-banking}"
SANDBOX_PARTNER="127.0.0.1:28081"
SANDBOX_HOLDER="127.0.0.1:28080"
COMPOSE_DEV=(docker compose -f "$ROOT/docker-compose.yml" -f "$ROOT/docker/compose.dev.yml")

say() { printf '\033[1;34m[stack]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[stack]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[stack]\033[0m %s\n' "$*" >&2; exit 1; }

# Valor de una variable: del entorno si está, si no del .env. Nunca se imprime.
env_value() {
  local name="$1" value="${!1:-}"
  if [ -z "$value" ] && [ -f "$ROOT/.env" ]; then
    value="$(grep -E "^${name}=" "$ROOT/.env" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
  fi
  printf '%s' "$value"
}

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

pid_alive() { [ -f "$STATE/$1.pid" ] && kill -0 "$(cat "$STATE/$1.pid")" 2>/dev/null; }

# Mata un proceso y todos sus hijos (`uv run` y `npm run` lanzan procesos hijos).
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

wait_for_http() {
  local url="$1" seconds="$2" i
  for i in $(seq 1 "$seconds"); do
    curl -s -o /dev/null -m 2 "$url" && return 0
    sleep 1
  done
  return 1
}

require() { command -v "$1" >/dev/null 2>&1 || die "falta '$1' en el PATH. $2"; }

# --------------------------------------------------------------------- up ----

start_postgres() {
  say "Postgres (Docker) en 127.0.0.1:$PG_PORT..."
  POSTGRES_PASSWORD="$(env_value POSTGRES_PASSWORD)" STACK_PG_PORT="$PG_PORT" \
    "${COMPOSE_DEV[@]}" up -d postgres >/dev/null
  local i
  for i in $(seq 1 60); do
    "${COMPOSE_DEV[@]}" exec -T postgres pg_isready -U agent_commerce >/dev/null 2>&1 && return 0
    sleep 1
  done
  die "Postgres no respondió en 60 s. Mirá: docker compose logs postgres"
}

start_sandbox() {
  [ -d "$AERARIUM_DIR/platform" ] || die "No encuentro el repo de Aerarium en $AERARIUM_DIR.
  Cloná: git clone https://github.com/Root1V/aerarium-agentic-banking.git \"$AERARIUM_DIR\"
  o indicá otro lugar con AERARIUM_DIR=..."
  local compose=(docker compose -f "$AERARIUM_DIR/platform/docker-compose.sandbox.yml")
  if [ ! -f "$AERARIUM_DIR/platform/.env" ]; then
    # Clave con la que el sandbox firma sus tokens: generada acá, nunca en un archivo público.
    echo "OAUTH_SIGNING_KEY=$(head -c 32 /dev/urandom | base64)" >"$AERARIUM_DIR/platform/.env"
  fi
  say "Sandbox de Aerarium (la primera vez compila, tarda unos minutos)..."
  PARTNER_PUBLISH="$SANDBOX_PARTNER" HOLDER_PUBLISH="$SANDBOX_HOLDER" "${compose[@]}" up --build -d >/dev/null 2>&1 \
    || die "No se pudo levantar el sandbox. Mirá: docker compose -f $AERARIUM_DIR/platform/docker-compose.sandbox.yml logs"
  wait_for_http "http://$SANDBOX_PARTNER/health" 120 || die "El sandbox no respondió en http://$SANDBOX_PARTNER/health"
  touch "$STATE/sandbox.started"

  # Secreto de la integración: el sandbox lo imprime UNA vez; si no lo tenemos, se rota.
  if [ ! -s "$STATE/aerarium_client_secret" ]; then
    say "Obteniendo un secreto nuevo de la integración (rotación; el anterior vale 7 días más)..."
    (umask 077; "${compose[@]}" run --rm bootstrap -client-id mercatus_sandbox -rotate 2>/dev/null \
      | sed -n 's/.*client_secret:[[:space:]]*//p' | tr -d '\r ' >"$STATE/aerarium_client_secret")
    [ -s "$STATE/aerarium_client_secret" ] || die "No se pudo obtener el secreto de la integración del sandbox."
  fi
  # Clave maestra con la que se cifran las claves de los agentes en la base.
  if [ ! -s "$STATE/aibank_master_key" ]; then
    (umask 077; uv run --quiet python -c \
      "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" >"$STATE/aibank_master_key")
    warn "Generé una clave maestra nueva en .stack/aibank_master_key. Respaldala: sin ella, las claves de"
    warn "los agentes guardadas en la base no se pueden descifrar y hay que registrar agentes nuevos."
  fi
}

backend_env() {
  local password jwt
  password="$(env_value POSTGRES_PASSWORD)"
  jwt="$(env_value AGENT_COMMERCE_JWT_SECRET_KEY)"
  [ -n "$jwt" ] || jwt="$(env_value JWT_SECRET_KEY)"
  if [ -z "$jwt" ]; then
    # Un secreto de desarrollo persistente: así las sesiones sobreviven a reinicios.
    [ -s "$STATE/jwt_secret" ] || (umask 077; head -c 48 /dev/urandom | base64 | tr -d '\n=+/' >"$STATE/jwt_secret")
    jwt="$(cat "$STATE/jwt_secret")"
  fi
  export AGENT_COMMERCE_DATABASE_URL="postgresql+psycopg://agent_commerce:${password:-agent_commerce}@127.0.0.1:${PG_PORT}/agent_commerce"
  export AGENT_COMMERCE_JWT_SECRET_KEY="$jwt"
  if [ -f "$STATE/sandbox.started" ]; then
    export AGENT_COMMERCE_AIBANK_BASE_URL="http://$SANDBOX_PARTNER"
    export AGENT_COMMERCE_AIBANK_HOLDER_URL="http://$SANDBOX_HOLDER"
    export AGENT_COMMERCE_AIBANK_CLIENT_ID="mercatus_sandbox"
    export AGENT_COMMERCE_AIBANK_CLIENT_SECRET="$(cat "$STATE/aerarium_client_secret")"
    export AGENT_COMMERCE_AIBANK_KEY_ENCRYPTION_KEY="$(cat "$STATE/aibank_master_key")"
  fi
}

prepare_database() {
  say "Migraciones y catálogo semilla..."
  (cd "$ROOT" && uv run --quiet alembic upgrade head >/dev/null 2>&1) || die "Fallaron las migraciones: uv run alembic upgrade head"
  (cd "$ROOT" && uv run --quiet agent-commerce catalog seed >/dev/null 2>&1) || true
  local admins
  admins="$(cd "$ROOT" && uv run --quiet python -c '
from sqlalchemy import func, select
from agent_commerce.db.models import UserModel
from agent_commerce.db.session import build_session_factory
db = build_session_factory()()
print(db.scalar(select(func.count()).select_from(UserModel)))
' 2>/dev/null || echo "?")"
  if [ "$admins" = "0" ]; then
    if [ -t 0 ]; then
      say "No hay usuario admin todavía. Creémoslo:"
      (cd "$ROOT" && uv run agent-commerce create-admin)
    else
      warn "No hay usuario admin. Creálo con: uv run agent-commerce create-admin"
    fi
  fi
}

start_backend() {
  port_busy "$API_PORT" && die "El puerto $API_PORT está ocupado. Usá otro: STACK_API_PORT=8001 scripts/stack.sh up"
  say "Backend (dashboard) en http://127.0.0.1:$API_PORT ..."
  # `cd` aparte (con `;`): con `cd && nohup ... &` iría a segundo plano toda la
  # cadena en una subshell que se queda esperando y retiene la salida del script.
  (cd "$ROOT"; nohup uv run agent-commerce dashboard --host 127.0.0.1 --port "$API_PORT" \
    </dev/null >"$STATE/logs/backend.log" 2>&1 & echo $! >"$STATE/backend.pid")
  wait_for_http "http://127.0.0.1:$API_PORT/docs" 60 || die "El backend no arrancó. Mirá: scripts/stack.sh logs backend"
}

start_frontend() {
  port_busy "$WEB_PORT" && die "El puerto $WEB_PORT está ocupado. Usá otro: STACK_WEB_PORT=5174 scripts/stack.sh up"
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    say "Instalando dependencias del frontend (una sola vez)..."
    npm --prefix "$ROOT/frontend" ci >/dev/null
  fi
  say "Frontend en http://localhost:$WEB_PORT ..."
  (cd "$ROOT"; AGENT_COMMERCE_API_URL="http://127.0.0.1:$API_PORT" nohup npm --prefix frontend run dev -- \
    --port "$WEB_PORT" --strictPort </dev/null >"$STATE/logs/frontend.log" 2>&1 & echo $! >"$STATE/frontend.pid")
  wait_for_http "http://localhost:$WEB_PORT" 60 || die "El frontend no arrancó. Mirá: scripts/stack.sh logs frontend"
}

cmd_up() {
  local sandbox=0 docker=0
  for arg in "$@"; do
    case "$arg" in
      --sandbox) sandbox=1 ;;
      --docker) docker=1 ;;
      *) die "Opción desconocida: $arg" ;;
    esac
  done
  [ "$sandbox" = 1 ] && [ "$docker" = 1 ] && die "--sandbox solo funciona en modo desarrollo (sin --docker)."
  require docker "Instalá Docker Desktop."
  mkdir -p "$STATE/logs"
  if [ -f "$STATE/mode" ] && { pid_alive backend || pid_alive frontend || [ "$(cat "$STATE/mode")" = docker ]; }; then
    die "El stack ya está arriba ($(cat "$STATE/mode")). Bajalo primero: scripts/stack.sh down"
  fi

  if [ "$docker" = 1 ]; then
    [ -n "$(env_value JWT_SECRET_KEY)" ] || die "El modo Docker necesita JWT_SECRET_KEY en .env."
    say "Todo en contenedores (docker-compose.yml)..."
    (cd "$ROOT" && docker compose up -d --build)
    echo docker >"$STATE/mode"
    wait_for_http "http://localhost:8000/docs" 120 || warn "La API todavía no responde; mirá: scripts/stack.sh logs docker"
    say "Listo. Dashboard: http://localhost:5173  ·  API: http://localhost:8000/docs"
    return
  fi

  require uv "Ver https://docs.astral.sh/uv/"
  require npm "Instalá Node.js."
  rm -f "$STATE/sandbox.started"
  echo dev >"$STATE/mode"
  start_postgres
  [ "$sandbox" = 1 ] && start_sandbox
  backend_env
  prepare_database
  start_backend
  start_frontend
  say "Listo."
  cmd_status
}

# ------------------------------------------------------------------- down ----

cmd_down() {
  local mode="dev"
  [ -f "$STATE/mode" ] && mode="$(cat "$STATE/mode")"
  if [ "$mode" = docker ]; then
    say "Bajando los contenedores (los datos de Postgres se conservan)..."
    (cd "$ROOT" && docker compose down)
  else
    local name
    for name in frontend backend; do
      if pid_alive "$name"; then
        say "Deteniendo $name..."
        kill_tree "$(cat "$STATE/$name.pid")"
      fi
      rm -f "$STATE/$name.pid"
    done
    say "Deteniendo Postgres (los datos se conservan)..."
    "${COMPOSE_DEV[@]}" stop postgres >/dev/null 2>&1 || true
    if [ -f "$STATE/sandbox.started" ]; then
      say "Deteniendo el sandbox de Aerarium (sus datos se conservan)..."
      docker compose -f "$AERARIUM_DIR/platform/docker-compose.sandbox.yml" stop >/dev/null 2>&1 || true
      rm -f "$STATE/sandbox.started"
    fi
  fi
  rm -f "$STATE/mode"
  say "Abajo."
}

# ----------------------------------------------------------------- status ----

line() { printf '  %-22s %s\n' "$1" "$2"; }

cmd_status() {
  local mode="(abajo)"
  [ -f "$STATE/mode" ] && mode="$(cat "$STATE/mode")"
  echo "Stack de Mercatus — modo: $mode"
  if [ ! -f "$STATE/mode" ]; then
    echo "  Nada corriendo. Levantalo con: scripts/stack.sh up [--sandbox] [--docker]"
    return
  fi
  if [ "$mode" = docker ]; then
    (cd "$ROOT" && docker compose ps)
    return
  fi
  if "${COMPOSE_DEV[@]}" exec -T postgres pg_isready -U agent_commerce >/dev/null 2>&1; then
    line "Postgres" "arriba · 127.0.0.1:$PG_PORT"
  else
    line "Postgres" "abajo"
  fi
  if pid_alive backend; then line "Backend" "arriba · http://127.0.0.1:$API_PORT/docs"; else line "Backend" "abajo"; fi
  if pid_alive frontend; then line "Dashboard" "arriba · http://localhost:$WEB_PORT"; else line "Dashboard" "abajo"; fi
  if [ -f "$STATE/sandbox.started" ] && curl -s -m 2 -o /dev/null "http://$SANDBOX_PARTNER/health"; then
    line "Banco (Aerarium)" "sandbox real · http://$SANDBOX_PARTNER (titular: http://$SANDBOX_HOLDER)"
  else
    line "Banco (Aerarium)" "simulado en memoria (usá --sandbox para el real)"
  fi
}

cmd_logs() {
  case "${1:-backend}" in
    backend | frontend) tail -n 50 -f "$STATE/logs/$1.log" ;;
    docker) (cd "$ROOT" && docker compose logs -f --tail 50) ;;
    *) die "Logs disponibles: backend, frontend, docker" ;;
  esac
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  down) cmd_down ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "${1:-backend}" ;;
  *)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
