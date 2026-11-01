from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agent_commerce.payments.aibank_http import AIBankHttpApi, AIBankHttpHolderChannel
from agent_commerce.payments.mock_aibank import MockAIBank
from tests.payments.aibank_env import AIBankEnv

# Un parámetro por implementación del puerto: los mismos tests de contrato
# corren contra el mock y, si hay credenciales en el entorno, contra el
# sandbox real de Aerarium (ver `docs/roadmap.md`, "Cliente HTTP").
_SANDBOX_ENV = (
    "AGENT_COMMERCE_AIBANK_BASE_URL",
    "AGENT_COMMERCE_AIBANK_HOLDER_URL",
    "AGENT_COMMERCE_AIBANK_CLIENT_ID",
    "AGENT_COMMERCE_AIBANK_CLIENT_SECRET",
)


@pytest.fixture(params=["mock", "sandbox"])
async def aibank(request: pytest.FixtureRequest) -> AsyncIterator[AIBankEnv]:
    if request.param == "mock":
        bank = MockAIBank()
        secret = bank.register_integration("mercatus_test")
        yield AIBankEnv(api=bank.client("mercatus_test", secret), holders=bank.holder_channel(), kind="mock")
        return

    missing = [name for name in _SANDBOX_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(f"sandbox de Aerarium sin configurar: faltan {', '.join(missing)}")
    api = AIBankHttpApi(
        base_url=os.environ["AGENT_COMMERCE_AIBANK_BASE_URL"],
        client_id=os.environ["AGENT_COMMERCE_AIBANK_CLIENT_ID"],
        client_secret=os.environ["AGENT_COMMERCE_AIBANK_CLIENT_SECRET"],
    )
    holders = AIBankHttpHolderChannel(
        base_url=os.environ["AGENT_COMMERCE_AIBANK_HOLDER_URL"],
        dev_key=os.environ.get("AGENT_COMMERCE_AIBANK_DEV_KEY"),
    )
    try:
        yield AIBankEnv(api=api, holders=holders, kind="sandbox")
    finally:
        await api.aclose()
        await holders.aclose()
