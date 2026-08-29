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

from agent_commerce.agentloop.loop import AgentLoop, AgentLoopError
from agent_commerce.auth.dependencies import get_current_user
from agent_commerce.auth.router import router as auth_router
from agent_commerce.catalog.models import ServiceListing
from agent_commerce.catalog.registry import InMemoryServiceRegistry
from agent_commerce.client.paying_agent import NoMatchingServiceError, PayingAgent
from agent_commerce.config import Protocol, Settings, get_settings
from agent_commerce.db.models import UserModel
from agent_commerce.db.session import get_db
from agent_commerce.llm.client import LLMClientError, PrometheusLLMClient
from agent_commerce.payments.factory import build_wallet_signer, get_payment_protocol
from agent_commerce.payments.wallets.base import WalletSigner
from agent_commerce.payments.wallets.circle_wallet import CircleWalletSigner
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner

from .adapters.sql_agent_store import SqlAgentStore
from .adapters.sql_catalog_store import SqlCatalogStore
from .adapters.sql_ledger_store import SqlLedgerStore
from .adapters.sql_llm_settings_store import SqlLlmSettingsStore
from .adapters.sql_wallet_settings_store import SqlWalletSettingsStore
from .ports import Agent, AgentConversation, AgentMessage, LlmSettings, WalletSettings

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


class CreateAgentRequest(BaseModel):
    name: str
    instructions: str = ""
    llm_model: str
    protocol: str
    spend_limit_usd: Decimal | None = None


class CreateConversationRequest(BaseModel):
    title: str = ""


class CreateMessageRequest(BaseModel):
    content: str


class UpdateLlmSettingsRequest(BaseModel):
    auth_base_url: str
    gateway_base_url: str
    client_id: str
    # None = conservar el secreto ya guardado (para poder editar el resto sin reescribirlo).
    client_secret: str | None = None
    allowed_models: list[str] = []


class UpdateWalletSettingsRequest(BaseModel):
    backend: str  # "local" | "circle"
    circle_api_key: str | None = None
    # None = conservar el secreto ya guardado (para poder editar el resto sin reescribirlo).
    circle_entity_secret: str | None = None
    circle_wallet_id: str | None = None


def _agent_to_dict(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "owner_user_id": agent.owner_user_id,
        "name": agent.name,
        "instructions": agent.instructions,
        "llm_model": agent.llm_model,
        "protocol": agent.protocol,
        "spend_limit_usd": str(agent.spend_limit_usd) if agent.spend_limit_usd is not None else None,
        "created_at": agent.created_at.isoformat(),
    }


def _conversation_to_dict(conversation: AgentConversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "agent_id": conversation.agent_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
    }


def _message_to_dict(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "trace": message.trace,
        "total_spent_usd": str(message.total_spent_usd) if message.total_spent_usd is not None else None,
        "created_at": message.created_at.isoformat(),
    }


def _llm_settings_to_dict(settings_row: LlmSettings) -> dict[str, Any]:
    return {
        "configured": True,
        "source": "db",
        "auth_base_url": settings_row.auth_base_url,
        "gateway_base_url": settings_row.gateway_base_url,
        "client_id": settings_row.client_id,
        "has_secret": True,
        "allowed_models": settings_row.allowed_models,
        "updated_at": settings_row.updated_at.isoformat(),
    }


def _build_llm_client(
    *, auth_base_url: str, gateway_base_url: str, client_id: str, client_secret: str
) -> PrometheusLLMClient:
    return PrometheusLLMClient(
        auth_base_url=auth_base_url,
        gateway_base_url=gateway_base_url,
        client_id=client_id,
        client_secret=client_secret,
    )


_LlmClientKey = tuple[str, str, str, str]


class _LlmClientHolder:
    """Caja mutable para el `PrometheusLLMClient` activo: `_get_llm_client`
    lo reconstruye sólo cuando `key` (URLs + client_id/secret efectivos)
    cambia respecto de la última vez -- así una edición desde
    `PUT /api/admin/llm-settings` toma efecto en el siguiente request sin
    reiniciar el proceso, pero mientras la config no cambie se reusa la
    misma conexión (y su caché de token OAuth2)."""

    def __init__(self, client: PrometheusLLMClient | None) -> None:
        self.client = client
        self.key: _LlmClientKey | None = None


def _wallet_settings_to_dict(settings_row: WalletSettings) -> dict[str, Any]:
    # El API key de Circle NUNCA se devuelve: autentica solo (como un
    # password), no es un identificador público como el `client_id` de
    # OAuth2 -- mismo tratamiento que `circle_entity_secret`.
    return {
        "backend": settings_row.backend,
        "has_circle_api_key": settings_row.circle_api_key is not None,
        "has_circle_entity_secret": settings_row.circle_entity_secret is not None,
        "circle_wallet_id": settings_row.circle_wallet_id,
        "updated_at": settings_row.updated_at.isoformat(),
    }


_WalletSignerKey = tuple[str, ...]


class _WalletSignerHolder:
    """Misma idea que `_LlmClientHolder` pero para el `WalletSigner` del
    COMPRADOR: se reconstruye solo cuando cambia la configuración efectiva
    (fila de `wallet_settings` si existe, si no `Settings.wallet_backend` de
    entorno) -- así una wallet Circle no vuelve a pedir su dirección por red
    en cada request, solo la primera vez que se usa esa configuración."""

    def __init__(self, signer: WalletSigner | None) -> None:
        self.signer = signer
        self.key: _WalletSignerKey | None = None


def _get_owned_agent(store: SqlAgentStore, agent_id: int, owner_user_id: int) -> Agent:
    agent = store.get_agent(agent_id)
    if agent is None or agent.owner_user_id != owner_user_id:
        raise HTTPException(404, f"No existe un agente con id {agent_id}")
    return agent


def _get_owned_conversation(store: SqlAgentStore, conversation_id: int, agent: Agent) -> AgentConversation:
    conversation = store.get_conversation(conversation_id)
    if conversation is None or conversation.agent_id != agent.id:
        raise HTTPException(404, f"No existe una conversación con id {conversation_id}")
    return conversation


def _build_prompt_with_history(prior_messages: list[AgentMessage], new_content: str) -> str:
    """Concatena los turnos previos como texto plano antes del mensaje nuevo.

    `AgentLoop.run()` (RM-12) razona sobre un único mensaje de usuario, sin
    noción de "conversación" -- para dar continuidad entre mensajes sin
    tocar su contrato, el historial se aplana a texto aquí, en la capa de
    API. Es una memoria simple (solo el texto de cada turno, no la traza
    completa de tool-use de turnos anteriores); una memoria más rica queda
    fuera del alcance de RM-14.
    """
    if not prior_messages:
        return new_content
    lines = [f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in prior_messages]
    return "Conversation so far:\n" + "\n".join(lines) + f"\n\nUser: {new_content}"


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
    # El COMPRADOR sí es configurable en caliente desde el dashboard (RM-19,
    # ver `_get_buyer_signer` más abajo) -- el vendedor de ejemplo no: ya
    # levantó sus servidores reales con `pay_to=seller_signers[name].address`
    # fijo al construir la app (unas líneas más abajo), así que cambiarle la
    # wallet en caliente no movería el `pay_to` que esos procesos ya están
    # anunciando. Extenderlo a también-dinámico queda para otra fase.

    seller_ports: dict[str, int] = {}
    seller_servers: list[uvicorn.Server] = []
    for name in _PROTOCOL_NAMES:
        seller_app = build_seller_app(protocol=protocols[name], pay_to=seller_signers[name].address)
        port = _free_port()
        seller_servers.append(_start_uvicorn(seller_app, port))
        seller_ports[name] = port

    # Cliente al gateway de Prometheus (RM-11) para el playground de agentes
    # (RM-14) -- opcional: sin credenciales configuradas, el resto del
    # dashboard sigue funcionando, solo los endpoints de /api/agents que
    # necesitan el LLM devuelven 500 explicando qué falta configurar.
    #
    # La conexión (URLs + client_id/secret + modelos habilitados) se guarda
    # en la tabla `llm_settings` vía PUT /api/admin/llm-settings -- así quien
    # administra el dashboard no necesita acceso al `.env` del servidor para
    # conectar un LLM, solo las credenciales que le dio quien administra
    # Prometheus. Si no hay fila en la DB todavía, se usan las variables de
    # entorno `AGENT_COMMERCE_LLM_*` como fallback (deploys que sí prefieren
    # configurarlo por `.env`). La DB manda una vez configurada.
    #
    # Deliberadamente NO se lee la DB al construir la app (a diferencia del
    # resto del estado que sí se arma acá, como `protocols`/`seller_signers`):
    # `build_dashboard_app` no depende de `Depends(get_db)`, así que abrir una
    # sesión acá usaría siempre la `Settings.database_url` real -- rompiendo
    # el patrón de tests que reemplazan `get_db` DESPUÉS de construir la app
    # (ver `tests/dashboard/conftest.py`). En cambio, el cliente se resuelve
    # de forma perezosa en cada request via `_get_llm_client(db)`, cacheado
    # mientras la configuración no cambie.
    llm_holder = _LlmClientHolder(None)
    wallet_signer_holder = _WalletSignerHolder(None)

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for server in seller_servers:
            server.should_exit = True
        if llm_holder.client is not None:
            await llm_holder.client.aclose()

    app = FastAPI(title="agent_commerce dashboard", lifespan=_lifespan)

    def _seller_url(protocol: str) -> str:
        return f"http://127.0.0.1:{seller_ports[protocol]}/summarize"

    async def _get_llm_client(db: Session) -> PrometheusLLMClient:
        settings_row = SqlLlmSettingsStore(db).get()
        if settings_row is not None:
            key = (
                settings_row.auth_base_url,
                settings_row.gateway_base_url,
                settings_row.client_id,
                settings_row.client_secret,
            )
        elif settings.llm_client_id and settings.llm_client_secret:
            key = (
                settings.llm_auth_base_url,
                settings.llm_gateway_base_url,
                settings.llm_client_id,
                settings.llm_client_secret.get_secret_value(),
            )
        else:
            raise HTTPException(
                500,
                "El playground de agentes requiere conectar un LLM: configuralo desde "
                "'Configurar LLM' en la página de Agentes, o con AGENT_COMMERCE_LLM_CLIENT_ID/"
                "AGENT_COMMERCE_LLM_CLIENT_SECRET -- ver .env.example.",
            )

        if llm_holder.key != key:
            old_client = llm_holder.client
            llm_holder.client = _build_llm_client(
                auth_base_url=key[0], gateway_base_url=key[1], client_id=key[2], client_secret=key[3]
            )
            llm_holder.key = key
            if old_client is not None:
                await old_client.aclose()

        assert llm_holder.client is not None
        return llm_holder.client

    def _get_buyer_signer(db: Session) -> WalletSigner:
        """El backend de wallet del COMPRADOR (RM-06/RM-19): fila de
        `wallet_settings` si existe, si no `Settings.wallet_backend` de
        entorno como fallback -- mismo patrón que `_get_llm_client`. Solo
        se reconstruye cuando la configuración efectiva cambia; una wallet
        Circle ya resuelta reusa su dirección cacheada sin volver a pedirla
        por red en cada request."""
        settings_row = SqlWalletSettingsStore(db).get()
        backend = settings_row.backend if settings_row is not None else settings.wallet_backend.value

        if backend == "circle":
            if settings_row is None or not (
                settings_row.circle_api_key
                and settings_row.circle_entity_secret
                and settings_row.circle_wallet_id
            ):
                raise HTTPException(
                    500,
                    "El backend de wallet 'circle' requiere configurarlo desde 'Configurar "
                    "wallet' en la página de Probar comprador (API key, entity secret y "
                    "wallet_id de Circle).",
                )
            key: _WalletSignerKey = (
                "circle",
                settings_row.circle_api_key,
                settings_row.circle_entity_secret,
                settings_row.circle_wallet_id,
            )
            if wallet_signer_holder.key != key:
                wallet_signer_holder.signer = CircleWalletSigner(
                    wallet_id=settings_row.circle_wallet_id,
                    api_key=settings_row.circle_api_key,
                    entity_secret=settings_row.circle_entity_secret,
                )
                wallet_signer_holder.key = key
        else:
            local_key = settings.buyer_private_key.get_secret_value() if settings.buyer_private_key else None
            key = ("local", local_key or "")
            if wallet_signer_holder.key != key:
                wallet_signer_holder.signer = LocalEoaSigner(private_key=local_key)
                wallet_signer_holder.key = key

        assert wallet_signer_holder.signer is not None
        return wallet_signer_holder.signer

    def _agent_catalog(protocol: str) -> InMemoryServiceRegistry:
        # Mismo servicio real que /api/test-call: el catálogo persistido
        # (CatalogStore) es metadata administrable, no invocable de verdad
        # (ver nota del módulo) -- el agente del playground busca/paga
        # exactamente el mismo text-summarizer real que "Probar comprador".
        listing = ServiceListing(
            id="text-summarizer",
            name="Text Summarizer",
            description="Resume un texto a N oraciones clave por extracción de frecuencia de palabras.",
            price_usd="$0.001",
            capability_tags=["summarize", "text", "research", "nlp"],
            method="POST",
            url=_seller_url(protocol),  # type: ignore[arg-type]
            protocols=[protocol],
        )
        return InMemoryServiceRegistry([listing])

    app.include_router(auth_router)

    api = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])

    @api.get("/stats")
    async def api_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
        store = SqlLedgerStore(db)
        return {"mode": settings.mode.value, "network": settings.network, **store.stats()}

    @api.get("/protocols")
    async def api_protocols(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
        # Si el backend de wallet Circle está mal configurado, no tiene
        # sentido tumbar esta vista general por eso -- se degrada a
        # `buyer_address: None` en vez de propagar el 500.
        try:
            buyer_address: str | None = _get_buyer_signer(db).address
        except HTTPException:
            buyer_address = None

        return [
            {
                "name": name,
                "label": _PROTOCOL_LABELS[name],
                "description": _PROTOCOL_DESCRIPTIONS[name],
                "network": settings.network,
                "mode": settings.mode.value,
                "seller_pay_to": seller_signers[name].address,
                "buyer_address": buyer_address,
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
        buyer_signer = _get_buyer_signer(db)

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
                # RM-19: con qué backend de wallet firmó el comprador -- así
                # se ve en el recibo, no hay que adivinarlo comparando
                # direcciones a mano.
                "wallet_backend": wallet_signer_holder.key[0] if wallet_signer_holder.key else None,
            },
        }

    @api.get("/agents/llm-models")
    async def api_llm_models(
        include_all: bool = False, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        """`include_all=true` se usa desde el diálogo de configuración (para
        elegir qué modelos habilitar) -- el resto de la app siempre ve la
        lista ya filtrada por `allowed_models` (si hay alguno configurado)."""
        client = await _get_llm_client(db)
        try:
            models = await client.list_models()
        except LLMClientError as exc:
            raise HTTPException(502, f"No se pudo listar los modelos de Prometheus: {exc}") from exc

        if not include_all:
            settings_row = SqlLlmSettingsStore(db).get()
            if settings_row is not None and settings_row.allowed_models:
                allowed_ids = set(settings_row.allowed_models)
                models = [m for m in models if m.get("id") in allowed_ids]

        return {"models": models}

    @api.get("/admin/llm-settings")
    async def api_get_llm_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
        settings_row = SqlLlmSettingsStore(db).get()
        if settings_row is not None:
            return _llm_settings_to_dict(settings_row)
        return {
            "configured": bool(settings.llm_client_id and settings.llm_client_secret),
            "source": "env" if settings.llm_client_id else "none",
            "auth_base_url": settings.llm_auth_base_url,
            "gateway_base_url": settings.llm_gateway_base_url,
            "client_id": settings.llm_client_id or "",
            "has_secret": bool(settings.llm_client_secret),
            "allowed_models": [],
            "updated_at": None,
        }

    @api.put("/admin/llm-settings")
    async def api_update_llm_settings(
        payload: UpdateLlmSettingsRequest, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        store = SqlLlmSettingsStore(db)
        try:
            updated = store.upsert(
                auth_base_url=payload.auth_base_url,
                gateway_base_url=payload.gateway_base_url,
                client_id=payload.client_id,
                client_secret=payload.client_secret,
                allowed_models=payload.allowed_models,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        old_client = llm_holder.client
        llm_holder.client = _build_llm_client(
            auth_base_url=updated.auth_base_url,
            gateway_base_url=updated.gateway_base_url,
            client_id=updated.client_id,
            client_secret=updated.client_secret,
        )
        if old_client is not None:
            await old_client.aclose()

        return _llm_settings_to_dict(updated)

    @api.get("/admin/wallet-settings")
    async def api_get_wallet_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
        settings_row = SqlWalletSettingsStore(db).get()
        if settings_row is not None:
            return _wallet_settings_to_dict(settings_row)
        return {
            "backend": settings.wallet_backend.value,
            "has_circle_api_key": False,
            "has_circle_entity_secret": False,
            "circle_wallet_id": None,
            "updated_at": None,
        }

    @api.put("/admin/wallet-settings")
    async def api_update_wallet_settings(
        payload: UpdateWalletSettingsRequest, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        if payload.backend not in ("local", "circle"):
            raise HTTPException(400, f"Backend de wallet desconocido: {payload.backend}")
        store = SqlWalletSettingsStore(db)
        try:
            updated = store.upsert(
                backend=payload.backend,
                circle_api_key=payload.circle_api_key,
                circle_entity_secret=payload.circle_entity_secret,
                circle_wallet_id=payload.circle_wallet_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        # No hace falta reconstruir el signer acá: `_get_buyer_signer` ya
        # detecta el cambio de configuración (por `key`) la próxima vez que
        # se use, igual que `_get_llm_client`.
        return _wallet_settings_to_dict(updated)

    @api.post("/agents", status_code=201)
    async def api_create_agent(
        payload: CreateAgentRequest,
        current_user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        if payload.protocol not in protocols:
            raise HTTPException(400, f"Protocolo desconocido: {payload.protocol}")
        store = SqlAgentStore(db)
        agent = store.create_agent(
            owner_user_id=current_user.id,
            name=payload.name,
            instructions=payload.instructions,
            llm_model=payload.llm_model,
            protocol=payload.protocol,
            spend_limit_usd=payload.spend_limit_usd,
        )
        return _agent_to_dict(agent)

    @api.get("/agents")
    async def api_list_agents(
        current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> list[dict[str, Any]]:
        store = SqlAgentStore(db)
        return [_agent_to_dict(a) for a in store.list_agents(owner_user_id=current_user.id)]

    @api.put("/agents/{agent_id}")
    async def api_update_agent(
        agent_id: int,
        payload: CreateAgentRequest,
        current_user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        if payload.protocol not in protocols:
            raise HTTPException(400, f"Protocolo desconocido: {payload.protocol}")
        store = SqlAgentStore(db)
        _get_owned_agent(store, agent_id, current_user.id)
        updated = store.update_agent(
            agent_id,
            name=payload.name,
            instructions=payload.instructions,
            llm_model=payload.llm_model,
            protocol=payload.protocol,
            spend_limit_usd=payload.spend_limit_usd,
        )
        assert updated is not None  # _get_owned_agent ya confirmó que existe
        return _agent_to_dict(updated)

    @api.delete("/agents/{agent_id}")
    async def api_delete_agent(
        agent_id: int, current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        store = SqlAgentStore(db)
        _get_owned_agent(store, agent_id, current_user.id)
        store.delete_agent(agent_id)
        return {"deleted": True, "id": agent_id}

    @api.post("/agents/{agent_id}/conversations", status_code=201)
    async def api_create_conversation(
        agent_id: int,
        payload: CreateConversationRequest,
        current_user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        store = SqlAgentStore(db)
        agent = _get_owned_agent(store, agent_id, current_user.id)
        conversation = store.create_conversation(agent_id=agent.id, title=payload.title)
        return _conversation_to_dict(conversation)

    @api.get("/agents/{agent_id}/conversations")
    async def api_list_conversations(
        agent_id: int, current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> list[dict[str, Any]]:
        store = SqlAgentStore(db)
        agent = _get_owned_agent(store, agent_id, current_user.id)
        return [_conversation_to_dict(c) for c in store.list_conversations(agent.id)]

    @api.get("/agents/{agent_id}/conversations/{conversation_id}/messages")
    async def api_list_messages(
        agent_id: int,
        conversation_id: int,
        current_user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        store = SqlAgentStore(db)
        agent = _get_owned_agent(store, agent_id, current_user.id)
        conversation = _get_owned_conversation(store, conversation_id, agent)
        return [_message_to_dict(m) for m in store.list_messages(conversation.id)]

    @api.post("/agents/{agent_id}/conversations/{conversation_id}/messages", status_code=201)
    async def api_create_message(
        agent_id: int,
        conversation_id: int,
        payload: CreateMessageRequest,
        current_user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        store = SqlAgentStore(db)
        agent = _get_owned_agent(store, agent_id, current_user.id)
        conversation = _get_owned_conversation(store, conversation_id, agent)
        client = await _get_llm_client(db)

        prior_messages = store.list_messages(conversation.id)
        store.add_message(conversation_id=conversation.id, role="user", content=payload.content)
        prompt = _build_prompt_with_history(prior_messages, payload.content)

        buyer_signer = _get_buyer_signer(db)
        async with PayingAgent(
            protocol=protocols[agent.protocol], signer=buyer_signer, catalog=_agent_catalog(agent.protocol)
        ) as paying_agent:
            loop = AgentLoop(
                llm=client,
                paying_agent=paying_agent,
                model=agent.llm_model,
                spend_limit_usd=agent.spend_limit_usd,
                extra_instructions=agent.instructions,
            )
            try:
                result = await loop.run(prompt)
            except AgentLoopError as exc:
                agent_message = store.add_message(
                    conversation_id=conversation.id,
                    role="agent",
                    content=f"El agente no pudo completar la respuesta: {exc}",
                )
                return _message_to_dict(agent_message)

        # Cada `call_service` exitoso de la traza es un pago real -- se
        # registra en la misma tabla `ledger_entries` de siempre (RM-13),
        # igual que ya hace /api/test-call, sin contabilidad duplicada.
        ledger = SqlLedgerStore(db)
        for step in result.trace:
            if step.action != "call_service" or not isinstance(step.observation, dict):
                continue
            observation = step.observation
            if "error" in observation:
                continue
            price_paid = observation.get("price_paid_usd")
            ledger.record(
                protocol=agent.protocol,
                capability=str(step.action_input.get("capability", "")),
                service_id=str(observation.get("service_id", "?")),
                payer=buyer_signer.address,
                pay_to=seller_signers[agent.protocol].address,
                amount_usd=Decimal(price_paid) if price_paid else Decimal(0),
                settlement_id=str(observation.get("settlement_id") or ""),
                status="ok",
            )

        trace_dicts = [
            {
                "turn": step.turn,
                "thought": step.thought,
                "action": step.action,
                "action_input": step.action_input,
                "observation": step.observation,
            }
            for step in result.trace
        ]
        agent_message = store.add_message(
            conversation_id=conversation.id,
            role="agent",
            content=result.answer,
            trace=trace_dicts,
            total_spent_usd=result.total_spent_usd,
        )
        return _message_to_dict(agent_message)

    app.include_router(api)
    return app
