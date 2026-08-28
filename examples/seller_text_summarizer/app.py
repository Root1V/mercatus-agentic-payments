"""Vendedor de ejemplo: un endpoint FastAPI monetizado a $0.001/llamada.

Muestra el único contrato que le importa a un vendedor real: escribir su
endpoint de negocio normal (`/summarize`) y llamar una vez a
`mount_payments(...)`. Todo lo demás -- qué protocolo de pago, mock o
testnet, qué wallet -- es responsabilidad de `agent_commerce.payments.factory`,
no de este archivo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import BaseModel

from agent_commerce.server.monetize import mount_payments

from .summarizer import summarize

if TYPE_CHECKING:
    from agent_commerce.payments.protocols.base import PaymentProtocol

PRICE_USD = "$0.001"
ROUTE = "POST /summarize"


class SummarizeRequest(BaseModel):
    text: str
    max_sentences: int = 2


def build_app(*, protocol: PaymentProtocol, pay_to: str) -> FastAPI:
    app = FastAPI(title="agent_commerce: text-summarizer (vendedor de ejemplo)")

    @app.post("/summarize")
    async def summarize_endpoint(request: SummarizeRequest) -> dict[str, str]:
        return {"summary": summarize(request.text, request.max_sentences)}

    @app.get("/catalog-entry")
    async def catalog_entry() -> dict[str, object]:
        """El propio servicio se autodescribe -- como haría un listing real
        de un marketplace de agentic commerce."""
        return {
            "id": "text-summarizer",
            "name": "Text Summarizer",
            "description": "Resume un texto a N oraciones clave.",
            "method": "POST",
            "price_usd": PRICE_USD,
            "capability_tags": ["summarize", "text", "research", "nlp"],
            "protocols": [protocol.name],
        }

    mount_payments(app, protocol=protocol, pay_to=pay_to, prices={ROUTE: PRICE_USD})
    return app


if __name__ == "__main__":
    import uvicorn

    from agent_commerce.config import get_settings
    from agent_commerce.payments.factory import build_wallet_signer, get_payment_protocol

    settings = get_settings()
    seller_signer = build_wallet_signer(role="seller", settings=settings)
    protocol = get_payment_protocol(settings)
    app = build_app(protocol=protocol, pay_to=seller_signer.address)

    print(f"[seller] pay_to={seller_signer.address} protocol={protocol.name} mode={settings.mode.value}")
    uvicorn.run(app, host="127.0.0.1", port=8901)
