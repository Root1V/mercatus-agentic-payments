"""Selección compartida de facilitator x402: memoria (mock) o HTTP remoto (testnet).

La usan ambos adaptadores de protocolo. `X402Protocol` liquida directo con
esto. `AP2Protocol` también: en el mundo real, la extensión oficial de
Google `a2a-x402` liquida los mandatos AP2 reutilizando exactamente el
mismo riel x402 -- este framework refleja esa misma composición en vez de
tener dos motores de liquidación separados.
"""

from __future__ import annotations

from typing import Any

from x402.http import FacilitatorConfig, HTTPFacilitatorClient

from ..config import Mode, Settings
from .mock_facilitator import MockFacilitator
from .wallets.local_eoa import LocalEoaSigner


def build_facilitator_client(settings: Settings) -> Any:
    if settings.mode is Mode.MOCK:
        return MockFacilitator(network=settings.network, facilitator_address=LocalEoaSigner().address)
    url = settings.facilitator_url or "https://x402.org/facilitator"
    return HTTPFacilitatorClient(FacilitatorConfig(url=url))
