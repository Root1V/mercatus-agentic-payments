"""Dashboard interactivo: backend JSON para probar `agent_commerce` en vivo.

Levanta el vendedor de ejemplo (`examples.seller_text_summarizer`) UNA VEZ
POR PROTOCOLO, cada uno como un servidor `uvicorn` real en su propio puerto
efímero (igual que `tests/conftest.py` y `examples/agent_to_agent_demo.py`)
-- así "probar como comprador" desde la UI ejercita el wire format completo
(402 -> firma -> reintento -> 200) contra un servicio real en la red, no una
simulación en memoria.

Nota técnica: al principio se intentó montar cada vendedor como sub-app vía
`app.mount("/seller/x402", seller_app)`, pero tanto el middleware de x402
(usa `scope["raw_path"]`) como el propio de AP2 (usaba `request.url.path`)
comparan contra la ruta COMPLETA, y Starlette moderno ya no reescribe
`scope["path"]` al montar una sub-aplicación (solo ajusta `root_path`) -- el
resultado era que el paywall se saltaba silenciosamente. Correr cada
vendedor en su propio puerto evita el problema de raíz.

Todas las rutas bajo `/api/` (salvo `/api/auth/login`) requieren un JWT
válido (`Depends(get_current_user)`). El frontend (React, en `frontend/`)
corre aparte -- este proceso ya no sirve HTML.

El catálogo persistido (`CatalogStore`, tabla `catalog_listings`) es
metadata administrable/de exhibición: crear un listing desde el dashboard
NO registra una ruta HTTP nueva ni lo hace pagable de verdad. `/api/test-call`
y `/api/seller-preview` siempre prueban el servicio real
`seller_text_summarizer` que este módulo levanta, independientemente de lo
que haya en el catálogo -- extender el catálogo a "cualquier listing es
invocable" es trabajo aparte, no incluido aquí.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from x402.http.utils import decode_payment_required_header

from agent_commerce.auth.dependencies import get_current_user
from agent_commerce.auth.router import router as auth_router
from agent_commerce.catalog.models import ServiceListing
from agent_commerce.catalog.registry import InMemoryServiceRegistry
from agent_commerce.client.paying_agent import NoMatchingServiceError, PayingAgent
from agent_commerce.config import Protocol, Settings, get_settings
from agent_commerce.db.session import get_db
from agent_commerce.payments.factory import build_wallet_signer, get_payment_protocol

from .adapters.sql_catalog_store import SqlCatalogStore
from .adapters.sql_ledger_store import SqlLedgerStore

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CATALOG_SEED_PATH = _REPO_ROOT / "data" / "catalog.sample.json"

_PROTOCOL_NAMES = ["x402", "ap2"]
_PROTOCOL_LABELS = {
    "x402": "x402 (Coinbase / Circle)",
    "ap2": "AP2 (Google)",
}
_PROTOCOL_DESCRIPTIONS = {
    "x402": (
        "Liquidación cripto directa sobre HTTP 402: el servidor responde 402 con el precio, "
        "el comprador firma una autorización EIP-3009 (USDC) y reintenta con el header "
        "X-PAYMENT; el servidor confirma con PAYMENT-RESPONSE."
    ),
    "ap2": (
        "Protocolo de autorización por mandatos, agnóstico al riel de pago: encadena "
        "IntentMandate -> CartMandate -> PaymentMandate, firmados y verificables. Este "
        "framework liquida el mandato delegando en el mismo motor x402 (como la extensión "
        "oficial a2a-x402 de Google)."
    ),
}

_SUMMARIZER_LISTING_BASE = {
    "id": "text-summarizer",
    "name": "Text Summarizer",
    "description": "Resume un texto a N oraciones clave por extracción de frecuencia de palabras.",
    "price_usd": "$0.001",
    "capability_tags": ["summarize", "text", "research", "nlp"],
}


class TestCallRequest(BaseModel):
    protocol: str
    capability: str = "summarize"
    text: str
    max_sentences: int = 2


class CreateCatalogListingRequest(BaseModel):
    id: str
    name: str
    description: str
    method: str = "POST"
    url: str
    price_usd: str
    capability_tags: list[str] = []
    protocols: list[str] = []
    provider_name: str = "agent_commerce demo"


class UpdateCatalogListingRequest(BaseModel):
    name: str
    description: str
    method: str = "POST"
    url: str
    price_usd: str
    capability_tags: list[str] = []
    protocols: list[str] = []
    provider_name: str = "agent_commerce demo"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    return server


def build_dashboard_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    repo_root_str = str(_REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    from examples.seller_text_summarizer.app import build_app as build_seller_app

    protocols = {
        name: get_payment_protocol(settings.model_copy(update={"protocol": Protocol(name)}))
        for name in _PROTOCOL_NAMES
    }
    seller_signers = {name: build_wallet_signer(role="seller", settings=settings) for name in _PROTOCOL_NAMES}
    buyer_signers = {name: build_wallet_signer(role="buyer", settings=settings) for name in _PROTOCOL_NAMES}

    seller_ports: dict[str, int] = {}
    seller_servers: list[uvicorn.Server] = []
    for name in _PROTOCOL_NAMES:
        seller_app = build_seller_app(protocol=protocols[name], pay_to=seller_signers[name].address)
        port = _free_port()
        seller_servers.append(_start_uvicorn(seller_app, port))
        seller_ports[name] = port

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for server in seller_servers:
            server.should_exit = True

    app = FastAPI(title="agent_commerce dashboard", lifespan=_lifespan)

    def _seller_url(protocol: str) -> str:
        return f"http://127.0.0.1:{seller_ports[protocol]}/summarize"

    app.include_router(auth_router)

    api = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])

    @api.get("/stats")
    async def api_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
        store = SqlLedgerStore(db)
        return {"mode": settings.mode.value, "network": settings.network, **store.stats()}

    @api.get("/protocols")
    async def api_protocols() -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "label": _PROTOCOL_LABELS[name],
                "description": _PROTOCOL_DESCRIPTIONS[name],
                "network": settings.network,
                "mode": settings.mode.value,
                "seller_pay_to": seller_signers[name].address,
                "buyer_address": buyer_signers[name].address,
                "endpoint": _seller_url(name),
            }
            for name in _PROTOCOL_NAMES
        ]

    @api.get("/catalog")
    async def api_catalog(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
        store = SqlCatalogStore(db)
        store.seed_from_json_if_empty(str(_DEFAULT_CATALOG_SEED_PATH))
        return [listing.model_dump(mode="json") for listing in store.list_all()]

    @api.post("/catalog", status_code=201)
    async def api_create_catalog_listing(
        payload: CreateCatalogListingRequest, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        store = SqlCatalogStore(db)
        if store.get(payload.id) is not None:
            raise HTTPException(409, f"Ya existe un listing con id '{payload.id}'")
        listing = ServiceListing.model_validate(payload.model_dump())
        created = store.create(listing, is_seed=False)
        return created.model_dump(mode="json")

    @api.put("/catalog/{listing_id}")
    async def api_update_catalog_listing(
        listing_id: str, payload: UpdateCatalogListingRequest, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        store = SqlCatalogStore(db)
        listing = ServiceListing.model_validate({"id": listing_id, **payload.model_dump()})
        updated = store.update(listing_id, listing)
        if updated is None:
            raise HTTPException(404, f"No existe un listing con id '{listing_id}'")
        return updated.model_dump(mode="json")

    @api.delete("/catalog/{listing_id}")
    async def api_delete_catalog_listing(listing_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
        store = SqlCatalogStore(db)
        deleted = store.delete(listing_id)
        if not deleted:
            raise HTTPException(404, f"No existe un listing con id '{listing_id}'")
        return {"deleted": True, "id": listing_id}

    @api.get("/ledger")
    async def api_ledger(limit: int = 50, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
        store = SqlLedgerStore(db)
        return [
            {**entry.__dict__, "timestamp": entry.timestamp.isoformat(), "amount_usd": str(entry.amount_usd)}
            for entry in store.recent(limit)
        ]

    @api.get("/seller-preview/{protocol}")
    async def api_seller_preview(protocol: str) -> dict[str, Any]:
        if protocol not in protocols:
            raise HTTPException(404, f"Protocolo desconocido: {protocol}")
        url = _seller_url(protocol)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"text": "vista previa sin pagar"})

        # x402 manda los requisitos de pago en el header `payment-required`
        # (base64), no en el body -- el body de un 402 x402 está vacío. AP2 sí
        # los manda en el body (`{"cartMandate": ...}`), así que ahí no hace
        # falta nada especial.
        body: Any = response.json() if response.content else None
        payment_required_header = response.headers.get("payment-required")
        if payment_required_header:
            body = decode_payment_required_header(payment_required_header).model_dump(mode="json")

        return {
            "status_code": response.status_code,
            "body": body,
            "pay_to": seller_signers[protocol].address,
            "price_usd": _SUMMARIZER_LISTING_BASE["price_usd"],
            "endpoint": url,
        }

    @api.post("/test-call")
    async def api_test_call(payload: TestCallRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
        if payload.protocol not in protocols:
            raise HTTPException(400, f"Protocolo desconocido: {payload.protocol}")

        ledger = SqlLedgerStore(db)
        listing = ServiceListing(
            id="text-summarizer",
            name="Text Summarizer",
            description="Resume un texto a N oraciones clave por extracción de frecuencia de palabras.",
            price_usd="$0.001",
            capability_tags=["summarize", "text", "research", "nlp"],
            method="POST",
            url=_seller_url(payload.protocol),  # type: ignore[arg-type]
            protocols=[payload.protocol],
        )
        catalog = InMemoryServiceRegistry([listing])
        buyer_signer = buyer_signers[payload.protocol]

        started = time.monotonic()
        try:
            async with PayingAgent(
                protocol=protocols[payload.protocol], signer=buyer_signer, catalog=catalog
            ) as agent:
                result = await agent.call_service(
                    payload.capability,
                    {"text": payload.text, "max_sentences": payload.max_sentences},
                )
        except NoMatchingServiceError as exc:
            ledger.record(
                protocol=payload.protocol, capability=payload.capability, service_id="?",
                payer=buyer_signer.address, pay_to="", amount_usd=Decimal(0), settlement_id="",
                status="error", detail=str(exc),
            )
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            ledger.record(
                protocol=payload.protocol, capability=payload.capability, service_id="text-summarizer",
                payer=buyer_signer.address, pay_to="", amount_usd=Decimal(0), settlement_id="",
                status="error", detail=str(exc),
            )
            raise HTTPException(502, str(exc)) from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        receipt = result.receipt
        pay_to = (receipt.pay_to if receipt and receipt.pay_to else seller_signers[payload.protocol].address)
        amount_usd = receipt.amount_usd if receipt else Decimal(0)
        settlement_id = receipt.settlement_id if receipt else ""

        entry = ledger.record(
            protocol=payload.protocol,
            capability=payload.capability,
            service_id=result.listing.id,
            payer=receipt.payer if receipt else buyer_signer.address,
            pay_to=pay_to,
            amount_usd=amount_usd,
            settlement_id=settlement_id,
            status="ok",
        )

        return {
            "ledger_entry_id": entry.id,
            "elapsed_ms": elapsed_ms,
            "result": result.data,
            "receipt": None
            if receipt is None
            else {
                "protocol": receipt.protocol,
                "network": receipt.network,
                "payer": receipt.payer,
                "pay_to": pay_to,
                "amount_usd": str(amount_usd),
                "settlement_id": receipt.settlement_id,
            },
        }

    app.include_router(api)
    return app
