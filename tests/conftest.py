from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi import FastAPI

from agent_commerce.config import Mode, Protocol, Settings
from agent_commerce.payments.factory import get_payment_protocol
from agent_commerce.payments.protocols.base import PaymentProtocol
from agent_commerce.payments.wallets.local_eoa import LocalEoaSigner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class RunningSeller:
    base_url: str
    pay_to: str
    protocol: PaymentProtocol
    settings: Settings


def _start_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    return server


@pytest.fixture(params=[Protocol.X402, Protocol.AP2])
def protocol_name(request: pytest.FixtureRequest) -> Protocol:
    """Parametriza cada test que la use por ambos protocolos soportados."""
    return request.param


@pytest.fixture
def mock_settings(protocol_name: Protocol) -> Settings:
    return Settings(mode=Mode.MOCK, protocol=protocol_name)


@pytest.fixture
def seller_server(mock_settings: Settings) -> Iterator[RunningSeller]:
    """Levanta el vendedor de ejemplo (seller_text_summarizer) con uvicorn real
    en un puerto efímero, protegido por el protocolo de pago parametrizado."""
    from examples.seller_text_summarizer.app import build_app

    protocol = get_payment_protocol(mock_settings)
    seller_signer = LocalEoaSigner()
    app = build_app(protocol=protocol, pay_to=seller_signer.address)

    port = _free_port()
    server = _start_uvicorn(app, port)
    try:
        yield RunningSeller(
            base_url=f"http://127.0.0.1:{port}",
            pay_to=seller_signer.address,
            protocol=protocol,
            settings=mock_settings,
        )
    finally:
        server.should_exit = True
