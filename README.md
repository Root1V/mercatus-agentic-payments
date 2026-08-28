# Mercatus — Agentic Payments Framework

*Production-grade dual-sided framework for agentic commerce — AI agents that discover, pay for,
and monetize services autonomously. Swappable payment-protocol adapters (x402 direct USDC
settlement, AP2 mandate-based authorization) and wallet backends behind clean ports/adapters.
FastAPI + React dashboard with Postgres persistence and JWT auth. No protocol or custodian
lock-in.*

A dual-sided (sell + buy) Python framework for "agentic commerce": AI agents that
automatically pay for APIs/services in USDC, without coupling to a single payment
protocol or a single wallet custodian.

> **Naming note**: the repository is called `mercatus-agentic-payments`, but the Python
> package, the CLI command, and the internal modules are still named `agent_commerce`/
> `agent-commerce` — every example in this README uses that technical name as-is.

Born out of an analysis of the business model of [Circle for Agents](https://agents.circle.com)
and the open [x402](https://github.com/coinbase/x402) protocol — see
[docs/business_model_analysis.md](docs/business_model_analysis.md) for the full critical
analysis, and [roadmap.md](roadmap.md) for the feature index (detail in
[docs/roadmap.md](docs/roadmap.md)).

## Why "no coupling to a single provider"

The agent-to-agent payments market doesn't have a clear winner yet: **x402**
(Coinbase/Circle, direct crypto settlement over HTTP 402) competes with **AP2**
(Google, payment-rail-agnostic authorization mandates). Betting the entire
architecture on just one of them, or on a single wallet custodian (Circle or
otherwise), is a real business risk. That's why this framework separates two
interchangeable ports:

- **`WalletSigner`** (`payments/wallets/`) — who signs. `LocalEoaSigner` (local key,
  the default, no external dependencies) or `CircleWalletSigner` (custody via Circle,
  optional `agent-commerce[circle]` extra).
- **`PaymentProtocol`** (`payments/protocols/`) — how the payment is negotiated/settled.
  `X402Protocol` or `AP2Protocol` (optional `agent-commerce[ap2]` extra).

`server/monetize.py` and `client/paying_agent.py` only ever code against these two
ports: switching protocol or wallet is a configuration change
(`AGENT_COMMERCE_PROTOCOL`, `AGENT_COMMERCE_WALLET_BACKEND`), never a code change.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ap2]"

# Agent-to-agent demo in mock mode (no credentials, no real funds)
python examples/agent_to_agent_demo.py --protocol x402
python examples/agent_to_agent_demo.py --protocol ap2

# Tests (mock mode; testnet tests are skipped without credentials)
pytest -m "not testnet"
```

## Structure

```
src/agent_commerce/
├── config.py            # Settings: protocol, mode (mock/testnet), wallet backend, DB, JWT
├── payments/
│   ├── wallets/          # WalletSigner port: local_eoa.py (default), circle_wallet.py (optional)
│   ├── protocols/        # PaymentProtocol port: x402_protocol.py, ap2_protocol.py
│   ├── mock_facilitator.py  # in-memory x402 facilitator: real EIP-712 verification, simulated settlement
│   └── factory.py        # composes WalletSigner + PaymentProtocol from Settings
├── server/monetize.py    # mount_payments(app, ...) — monetizes a FastAPI endpoint
├── client/paying_agent.py# PayingAgent — discovers and pays catalog services
├── catalog/               # ServiceListing / ServiceRegistry (simulated marketplace)
├── db/                    # SQLAlchemy 2.0 models (users, catalog_listings, ledger_entries)
├── auth/                  # JWT login (no self-registration), admin bootstrap
└── dashboard/             # interactive dashboard backend (see below)
examples/
├── seller_text_summarizer/  # example seller: POST /summarize at $0.001/call
├── buyer_research_agent/     # example buyer
└── agent_to_agent_demo.py    # orchestrates both end to end
frontend/                     # React dashboard (Vite + TS + Tailwind), see below
migrations/                   # Alembic
```

## Interactive dashboard

A web panel to try out each protocol, each role (buyer/seller), the service
catalog, and payment history, with its own login and Postgres-backed
persistence.

**Backend** (FastAPI + SQLAlchemy 2.0 + Alembic + JWT), managed with [`uv`](https://docs.astral.sh/uv/):

```bash
docker compose up -d postgres          # or any Postgres instance you already have
cp .env.example .env                    # fill in AGENT_COMMERCE_JWT_SECRET_KEY

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
npm run dev                              # http://localhost:5173 (proxies /api -> :8000)
```

**Everything together with Docker Compose**:

```bash
cp .env.example .env   # fill in POSTGRES_PASSWORD and JWT_SECRET_KEY
docker compose up --build
docker compose exec api agent-commerce create-admin   # one-time setup
```

See [docs/business_model_analysis.md](docs/business_model_analysis.md) for why
`WalletSigner`/`PaymentProtocol` are split into ports, and why the dashboard leaves out
Celery/Redis (there's no real background work in this project).

## Mock mode vs. testnet

In mock mode (`AGENT_COMMERCE_MODE=mock`, the default) everything runs in a single
process with no network or credentials required: `MockFacilitator` performs real
EIP-712 signature verification but settles against in-memory balances. In testnet mode
(`AGENT_COMMERCE_MODE=testnet`) the seller verifies/settles against a real x402
facilitator and the buyer can sign with a funded local key or a real Circle wallet —
see `.env.example`. This second path never runs in this repo without the user
supplying their own credentials and explicitly authorizing each step.

## Known limitations

- The AP2 adapter (`payments/protocols/ap2_protocol.py`) is a reference
  implementation: it uses the real pydantic types from the `ap2` package (Intent/Cart/
  Payment mandates), but negotiates over HTTP 402 instead of Google's official A2A
  transport, so this framework can share the same discovery mechanism with x402.
- `catalog/circle_marketplace.py` is a stub: no public discovery API for
  agents.circle.com was confirmed.
- `payments/wallets/circle_wallet.py` signs EIP-712 against a method name that hasn't
  been verified against real Circle credentials yet (see `docs/roadmap.md`, RM-06).

## Author

**Emeric V. Espiritu Santiago** — [@Root1V](https://github.com/Root1V)

## License

MIT — see [LICENSE](LICENSE).
