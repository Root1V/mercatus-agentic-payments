#!/usr/bin/env python3
"""Demo agente-a-agente de punta a punta.

Levanta el vendedor de ejemplo (`seller_text_summarizer`) con un servidor
HTTP real (uvicorn, no in-process) en un puerto efímero, y hace que el
comprador de ejemplo (`buyer_research_agent`) lo llame: ve el 402, paga
automáticamente, recibe el resultado, e imprime un "ledger" del pago.

Uso:
    python examples/agent_to_agent_demo.py --protocol x402 --mode mock
    python examples/agent_to_agent_demo.py --protocol ap2  --mode mock
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from agent_commerce.catalog.registry import InMemoryServiceRegistry
from agent_commerce.config import Mode, Protocol, Settings
from agent_commerce.payments.factory import (
    build_payer_credential,
    get_aibank_protocol,
    get_payment_protocol,
)
from examples.buyer_research_agent.agent import ResearchAgent
from examples.seller_text_summarizer.app import build_app

_TEXT = (
    "El protocolo x402 revive el codigo de estado HTTP 402 para que agentes de IA "
    "paguen APIs automaticamente. Circle integra USDC como riel de liquidacion. "
    "AP2 de Google agrega una capa de mandatos de autorizacion agnostica al riel "
    "de pago. Ninguno de los dos ha ganado todavia la carrera de estandares."
)


def _run_seller(app, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server


async def run_demo(protocol_name: str, mode_name: str, port: int) -> None:
    settings = Settings(protocol=Protocol(protocol_name), mode=Mode(mode_name))
    is_aibank = settings.protocol is Protocol.AIBANK

    # Para AIBank, vendedor y comprador tienen que compartir la MISMA
    # instancia de `AIBankProtocol` (y por lo tanto el mismo `MockAIBank` en
    # memoria): a diferencia de x402/AP2 (donde solo el facilitator del lado
    # vendedor importa -- el comprador únicamente firma), acá el comprador
    # llama directo al banco para autorizar+capturar, así que si tuviera su
    # propio banco en memoria por separado el vendedor nunca encontraría esa
    # autorización. Por eso una sola llamada a `get_aibank_protocol`, nunca
    # dos. x402/AP2 sí toleran instancias separadas por rol (ver
    # `get_payment_protocol`).
    seller_protocol = get_aibank_protocol(settings) if is_aibank else get_payment_protocol(settings)
    buyer_protocol = seller_protocol if is_aibank else get_payment_protocol(settings)
    seller_signer = build_payer_credential(role="seller", settings=settings)
    buyer_signer = build_payer_credential(role="buyer", settings=settings)

    app = build_app(protocol=seller_protocol, pay_to=seller_signer.address)  # type: ignore[arg-type]
    server = _run_seller(app, "127.0.0.1", port)

    catalog = InMemoryServiceRegistry.from_json_file(
        Path(__file__).resolve().parent.parent / "data" / "catalog.sample.json"
    )
    # El catálogo semilla apunta a localhost:8901 por defecto; lo reescribimos
    # al puerto efímero real que acabamos de levantar.
    for listing in catalog.all():
        listing.url = str(listing.url).replace(":8901", f":{port}")  # type: ignore[assignment]

    print(f"== agent_commerce demo == protocolo={protocol_name} modo={mode_name}")
    print(f"vendedor pay_to = {seller_signer.address}")
    print(f"comprador       = {buyer_signer.address}")
    print()

    async with ResearchAgent(
        protocol=buyer_protocol,  # type: ignore[arg-type]
        signer=buyer_signer,  # type: ignore[arg-type]
        catalog=catalog,
    ) as agent:
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

    server.should_exit = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", choices=["x402", "ap2", "aibank"], default="x402")
    parser.add_argument("--mode", choices=["mock", "testnet"], default="mock")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    asyncio.run(run_demo(args.protocol, args.mode, args.port))


if __name__ == "__main__":
    main()
