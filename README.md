# Mercatus — Agentic Payments Framework

*Production-grade dual-sided framework for agentic commerce — AI agents that discover, pay for,
and monetize services autonomously. Swappable payment-protocol adapters (x402 direct USDC
settlement, AP2 mandate-based authorization) and wallet backends behind clean ports/adapters.
FastAPI + React dashboard with Postgres persistence and JWT auth. No protocol or custodian
lock-in.*

Framework Python de doble cara (vender + comprar) para "agentic commerce": agentes de
IA que pagan automáticamente por APIs/servicios en USDC, sin acoplarse a un único
protocolo de pago ni a un único custodio de wallet.

> **Nota de nombres**: el repositorio se llama `mercatus-agentic-payments`, pero el paquete
> Python, el comando CLI y los módulos internos se siguen llamando `agent_commerce`/
> `agent-commerce` -- todos los ejemplos de este README usan ese nombre técnico tal cual.

Nace del análisis del modelo de negocio de [Circle for Agents](https://agents.circle.com)
y del protocolo abierto [x402](https://github.com/coinbase/x402) — ver
[docs/business_model_analysis.md](docs/business_model_analysis.md) para el análisis
crítico completo, y [roadmap.md](roadmap.md) para el índice de features
(detalle en [docs/roadmap.md](docs/roadmap.md)).

## Por qué "sin acoplamiento a un proveedor"

El mercado de pagos agente-a-agente todavía no tiene un ganador claro: **x402**
(Coinbase/Circle, liquidación cripto directa sobre HTTP 402) compite con **AP2**
(Google, mandatos de autorización agnósticos al riel de pago). Apostar toda la
arquitectura a uno solo, o a un único custodio de wallet (Circle u otro), es un riesgo
de negocio real. Por eso este framework separa dos puertos intercambiables:

- **`WalletSigner`** (`payments/wallets/`) — quién firma. `LocalEoaSigner` (clave local,
  por defecto, sin dependencias externas) o `CircleWalletSigner` (custodia vía Circle,
  extra opcional `agent-commerce[circle]`).
- **`PaymentProtocol`** (`payments/protocols/`) — cómo se negocia/liquida el pago.
  `X402Protocol` o `AP2Protocol` (extra opcional `agent-commerce[ap2]`).

`server/monetize.py` y `client/paying_agent.py` programan solo contra estos dos
puertos: cambiar de protocolo o de wallet es un cambio de configuración
(`AGENT_COMMERCE_PROTOCOL`, `AGENT_COMMERCE_WALLET_BACKEND`), nunca de código.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ap2]"

# Demo agente-a-agente en modo mock (sin credenciales, sin fondos reales)
python examples/agent_to_agent_demo.py --protocol x402
python examples/agent_to_agent_demo.py --protocol ap2

# Tests (modo mock; los de testnet se saltan si no hay credenciales)
pytest -m "not testnet"
```

## Estructura

```
src/agent_commerce/
├── config.py            # Settings: protocolo, modo (mock/testnet), backend de wallet, DB, JWT
├── payments/
│   ├── wallets/          # puerto WalletSigner: local_eoa.py (default), circle_wallet.py (opcional)
│   ├── protocols/        # puerto PaymentProtocol: x402_protocol.py, ap2_protocol.py
│   ├── mock_facilitator.py  # facilitator x402 en memoria: firma EIP-712 real, settle simulado
│   └── factory.py        # compone WalletSigner + PaymentProtocol según Settings
├── server/monetize.py    # mount_payments(app, ...) — monetiza un endpoint FastAPI
├── client/paying_agent.py# PayingAgent — descubre y paga servicios del catálogo
├── catalog/               # ServiceListing / ServiceRegistry (marketplace simulado)
├── db/                    # modelos SQLAlchemy 2.0 (users, catalog_listings, ledger_entries)
├── auth/                  # login JWT (sin auto-registro), bootstrap de admin
└── dashboard/             # backend del dashboard interactivo (ver más abajo)
examples/
├── seller_text_summarizer/  # vendedor de ejemplo: POST /summarize a $0.001/llamada
├── buyer_research_agent/     # comprador de ejemplo
└── agent_to_agent_demo.py    # orquesta ambos extremo a extremo
frontend/                     # dashboard React (Vite + TS + Tailwind), ver más abajo
migrations/                   # Alembic
```

## Dashboard interactivo

Un panel web para probar cada protocolo, cada rol (comprador/vendedor), el catálogo y el
historial de pagos, con login propio y persistencia en Postgres.

**Backend** (FastAPI + SQLAlchemy 2.0 + Alembic + JWT), gestionado con [`uv`](https://docs.astral.sh/uv/):

```bash
docker compose up -d postgres          # o cualquier Postgres propio
cp .env.example .env                    # completá AGENT_COMMERCE_JWT_SECRET_KEY

uv sync --extra dashboard --extra dev
uv run alembic upgrade head
uv run agent-commerce create-admin --username admin --password ...
uv run agent-commerce catalog seed
uv run agent-commerce dashboard          # http://127.0.0.1:8000
```

**Frontend** (React 19 + Vite + TypeScript + Tailwind + TanStack Query + react-router-dom):

```bash
cd frontend
npm install
npm run dev                              # http://localhost:5173 (proxy /api -> :8000)
```

**Todo junto con Docker Compose**:

```bash
cp .env.example .env   # completá POSTGRES_PASSWORD y JWT_SECRET_KEY
docker compose up --build
docker compose exec api agent-commerce create-admin   # una sola vez
```

Ver [docs/business_model_analysis.md](docs/business_model_analysis.md) para el porqué de
separar `WalletSigner`/`PaymentProtocol` como puertos, y por qué el dashboard omite
Celery/Redis (no hay ningún trabajo de fondo real en este proyecto).

## Modo mock vs. testnet

En modo mock (`AGENT_COMMERCE_MODE=mock`, default) todo corre en un solo proceso sin
red ni credenciales: el `MockFacilitator` verifica firmas EIP-712 reales pero liquida
sobre saldos en memoria. En modo testnet (`AGENT_COMMERCE_MODE=testnet`) el vendedor
verifica/liquida contra un facilitator x402 real y el comprador puede firmar con una
clave local financiada o con una wallet Circle real — ver `.env.example`. Esta segunda
vía no se ejecuta en este repo sin que el usuario provea sus propias credenciales y
autorice cada paso explícitamente.

## Limitaciones conocidas

- El adaptador AP2 (`payments/protocols/ap2_protocol.py`) es una implementación de
  referencia: usa los tipos pydantic reales del paquete `ap2` (mandatos
  Intent/Cart/Payment), pero transporta la negociación sobre HTTP 402 en vez del
  transporte A2A oficial de Google, para poder compartir el mismo mecanismo de
  descubrimiento que x402 dentro de este framework.
- `catalog/circle_marketplace.py` es un stub: no se confirmó una API de discovery
  pública de agents.circle.com.
- `payments/wallets/circle_wallet.py` firma EIP-712 contra un nombre de método aún no
  verificado con credenciales reales de Circle (ver `docs/roadmap.md`, RM-06).
