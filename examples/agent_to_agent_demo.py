#!/usr/bin/env python3
"""Demo agente-a-agente de punta a punta.

Levanta el vendedor de ejemplo (`seller_text_summarizer`) con un servidor
HTTP real (uvicorn, no in-process) en un puerto efímero, y hace que el
comprador de ejemplo (`buyer_research_agent`) lo llame: ve el 402, paga
automáticamente, recibe el resultado, e imprime un "ledger" del pago.

Con `--aibank-model mandate` (solo AP2 sobre AIBank) recorre el modelo B
completo (`13-spec-modelos-a-y-b.md` §3): pide permiso al titular, simula
su decisión (no hay app de AIBank todavía) y paga varias veces sobre la
cuenta del cliente hasta toparse con el límite que el titular concedió.

Uso:
    python examples/agent_to_agent_demo.py --protocol x402 --mode mock
    python examples/agent_to_agent_demo.py --protocol ap2  --mode mock
    python examples/agent_to_agent_demo.py --protocol ap2 --ap2-settlement aibank --aibank-model mandate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from agent_commerce.catalog.registry import InMemoryServiceRegistry
from agent_commerce.config import Mode, Protocol, Settings, SettlementRail
from agent_commerce.payments.aibank_credential import AIBankMandateCredential
from agent_commerce.payments.factory import build_payer_credential, get_payment_protocol
from agent_commerce.payments.mock_aibank import AIBankError
from agent_commerce.payments.protocols.ap2_protocol import AP2Protocol
from examples.buyer_research_agent.agent import ResearchAgent
from examples.seller_text_summarizer.app import build_app

_TEXT = (
    "El protocolo x402 revive el codigo de estado HTTP 402 para que agentes de IA "
    "paguen APIs automaticamente. Circle integra USDC como riel de liquidacion. "
    "AP2 de Google agrega una capa de mandatos de autorizacion agnostica al riel "
    "de pago. Ninguno de los dos ha ganado todavia la carrera de estandares."
)

# Lo que el titular lee literal en la pantalla de aprobación del banco.
_MANDATE_PURPOSE = "Agente de investigación de la demo de Mercatus: resúmenes de texto"

# Mismo criterio que `frontend/src/lib/apiError.ts`: decir quién arregla
# cada rechazo -- sobre todo, no confundir falta de permiso con falta de saldo.
_AIBANK_ERROR_EXPLANATIONS = {
    "mandate_limit_exceeded": (
        "el pago supera el permiso que dio el titular. No es falta de saldo: "
        "hay que pedirle una ampliación (o cobrar menos)."
    ),
    "mandate_revoked": "el titular revocó el permiso. Hay que pedirle consentimiento de nuevo.",
    "mandate_expired": "el permiso del titular venció. Hay que pedirle consentimiento de nuevo.",
    "insufficient_funds": "la cuenta del titular no tiene saldo. Esto sí es falta de dinero.",
    "cannot_raise_requested_limits": "el titular puede bajar los topes pedidos, nunca subirlos.",
}


@dataclass(frozen=True)
class MandateDemo:
    """Parámetros del recorrido del modelo B. `granted_max_total=None` =
    el titular concede exactamente lo pedido; un valor menor simula que
    bajó el tope en la app del banco (nunca puede subirlo)."""

    max_per_operation: Decimal = Decimal("0.001")
    max_total: Decimal = Decimal("0.003")
    granted_max_total: Decimal | None = None
    payments: int = 4
    titular_rejects: bool = False
    revoke_after: int | None = None


def _run_seller(app, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server


async def run_demo(
    protocol_name: str,
    mode_name: str,
    port: int,
    *,
    ap2_settlement: str = "x402",
    mandate: MandateDemo | None = None,
) -> None:
    settings = Settings(
        protocol=Protocol(protocol_name), mode=Mode(mode_name), ap2_settlement=SettlementRail(ap2_settlement)
    )
    # Con ap2_settlement=aibank, vendedor y comprador tienen que compartir la
    # MISMA instancia de `AP2Protocol` (y por lo tanto el mismo `MockAIBank`
    # en memoria): a diferencia de x402 puro (donde solo el facilitator del
    # lado vendedor importa -- el comprador únicamente firma), en ese riel el
    # comprador llama directo al banco para autorizar+capturar, así que si
    # tuviera su propio banco en memoria por separado el vendedor nunca
    # encontraría esa autorización. Por eso una sola llamada a
    # `get_payment_protocol`, nunca dos, cuando el riel es aibank -- x402
    # puro sí tolera instancias separadas por rol.
    shares_state = settings.protocol is Protocol.AP2 and settings.ap2_settlement is SettlementRail.AIBANK
    if mandate is not None and not shares_state:
        raise ValueError("el modelo B (cuenta del cliente) solo existe con --protocol ap2 --ap2-settlement aibank")
    seller_protocol = get_payment_protocol(settings)
    buyer_protocol = seller_protocol if shares_state else get_payment_protocol(settings)
    seller_signer = build_payer_credential(role="seller", settings=settings)

    app = build_app(protocol=seller_protocol, pay_to=seller_signer.address)
    server = _run_seller(app, "127.0.0.1", port)

    catalog = InMemoryServiceRegistry.from_json_file(
        Path(__file__).resolve().parent.parent / "data" / "catalog.sample.json"
    )
    # El catálogo semilla apunta a localhost:8901 por defecto; lo reescribimos
    # al puerto efímero real que acabamos de levantar.
    for listing in catalog.all():
        listing.url = str(listing.url).replace(":8901", f":{port}")  # type: ignore[assignment]

    try:
        print(f"== agent_commerce demo == protocolo={protocol_name} modo={mode_name}")
        if mandate is not None:
            assert isinstance(seller_protocol, AP2Protocol)
            print("riel=aibank · modelo B: paga la cuenta del cliente, con permiso de su titular")
            print(f"vendedor pay_to = {seller_signer.address}")
            # `shares_state` garantiza que comprador y vendedor usan esta misma instancia.
            await _run_mandate_flow(seller_protocol, catalog, mandate)
            return

        buyer_signer = build_payer_credential(role="buyer", settings=settings)
        print(f"vendedor pay_to = {seller_signer.address}")
        print(f"comprador       = {buyer_signer.address}")
        print()

        async with ResearchAgent(protocol=buyer_protocol, signer=buyer_signer, catalog=catalog) as agent:
            result = await agent.summarize(_TEXT, max_sentences=2)

        print("--- resultado de negocio ---")
        print(result.data["summary"])
        print()
        print("--- ledger de pago ---")
        receipt = result.receipt
        if receipt is None:
            print("(sin recibo -- revisa la configuración del protocolo)")
        else:
            print(f"protocolo:        {receipt.protocol}")
            print(f"red:              {receipt.network}")
            print(f"pagador:          {receipt.payer}")
            print(f"receptor:         {receipt.pay_to or seller_signer.address}")
            print(f"monto:            ${receipt.amount_usd}")
            print(f"id de liquidación:{receipt.settlement_id}")
    finally:
        server.should_exit = True


async def _run_mandate_flow(protocol: AP2Protocol, catalog: InMemoryServiceRegistry, options: MandateDemo) -> None:
    """Los 4 pasos del modelo B (doc 13 §3), en el orden en que ocurren en
    producción. Solo el paso 2 es simulado: en AIBank real lo hace el
    titular en SU app, y Mercatus se entera haciendo polling."""
    bank = protocol.bank
    print()
    print("--- 1. Mercatus pide permiso (sin elegir cuenta: la elige el titular) ---")
    request = bank.request_consent(
        currency="USD",
        max_per_operation=options.max_per_operation,
        max_total=options.max_total,
        purpose=_MANDATE_PURPOSE,
    )
    print(f"solicitud:        {request.id}")
    print(f"código titular:   {request.handoff_code}")
    print(f"tope por pago:    ${request.max_per_operation}")
    print(f"tope total:       ${request.max_total}")
    print(f"propósito:        {request.purpose}")

    print()
    print("--- 2. El titular decide [simulador: reemplaza la app de AIBank] ---")
    if options.titular_rejects:
        request = bank.simulate_titular_rejection(consent_request_id=request.id)
        print(f"estado:           {request.status}")
        print("El titular rechazó el permiso: no nace ningún mandato, el agente no puede pagar.")
        return

    holder_account_id = f"acc_{uuid.uuid4().hex[:12]}"
    try:
        mandate = bank.simulate_titular_approval(
            consent_request_id=request.id,
            account_id=holder_account_id,
            max_total=options.granted_max_total,
        )
    except AIBankError as exc:
        code = str(exc)
        print(f"el banco rechazó la aprobación ({code}) -- {_AIBANK_ERROR_EXPLANATIONS.get(code, code)}")
        return
    granted_note = "" if mandate.max_total == request.max_total else f" (pedido: ${request.max_total})"
    print(f"aprobado sobre la cuenta {mandate.account_id}")
    print(f"mandato:          {mandate.id}")
    print(f"tope total:       ${mandate.max_total}{granted_note}")
    print(f"vence:            {datetime.fromtimestamp(mandate.expires_at, tz=UTC):%Y-%m-%d %H:%M} UTC")

    print()
    print("--- 3. El agente paga con el permiso, desde la cuenta del cliente ---")
    credential = AIBankMandateCredential(mandate_id=mandate.id, account_id=mandate.account_id)
    async with ResearchAgent(protocol=protocol, signer=credential, catalog=catalog) as agent:
        for number in range(1, options.payments + 1):
            label = f"pago {number}/{options.payments}:"
            try:
                result = await agent.summarize(_TEXT, max_sentences=2)
            except AIBankError as exc:
                code = str(exc)
                explanation = _AIBANK_ERROR_EXPLANATIONS.get(code, "rechazado por el banco.")
                print(f"{label} RECHAZADO ({code}) -- {explanation}")
            else:
                usage = bank.mandate_usage(mandate.id)
                settlement = f" · liquidación {result.receipt.settlement_id}" if result.receipt else ""
                print(
                    f"{label} ok · consumido ${usage.consumed} de ${mandate.max_total} "
                    f"· quedan ${usage.remaining}{settlement}"
                )

            if options.revoke_after == number:
                bank.revoke_mandate(mandate.id)
                print("[simulador] el titular revoca el permiso desde la app de AIBank")

    print()
    print("--- 4. Consumo final del mandato ---")
    usage = bank.mandate_usage(mandate.id)
    print(f"estado:           {mandate.status}")
    print(f"consumido:        ${usage.consumed} de ${mandate.max_total}")
    print(f"quedan:           ${usage.remaining}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--protocol", choices=["x402", "ap2"], default="x402")
    parser.add_argument(
        "--ap2-settlement",
        choices=["x402", "aibank"],
        default="x402",
        help="Solo con --protocol ap2: riel de liquidación (RM-18).",
    )
    parser.add_argument(
        "--aibank-model",
        choices=["omnibus", "mandate"],
        default="omnibus",
        help="Solo con --ap2-settlement aibank: cuenta de Mercatus (A) o del cliente (B).",
    )
    parser.add_argument("--mode", choices=["mock", "testnet"], default="mock")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    mandate = MandateDemo() if args.aibank_model == "mandate" else None
    asyncio.run(
        run_demo(args.protocol, args.mode, args.port, ap2_settlement=args.ap2_settlement, mandate=mandate)
    )


if __name__ == "__main__":
    main()
