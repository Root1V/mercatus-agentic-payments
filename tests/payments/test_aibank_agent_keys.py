"""Las claves de los agentes, guardadas cifradas (`payments/aibank_agent_keys.py`):
que un reinicio reuse el mismo agente, que lo guardado no sirva sin la clave
maestra, y que una rotación nunca deje guardada una clave que el banco ya no
acepta."""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from agent_commerce.config import Mode, Protocol, Settings, SettlementRail
from agent_commerce.payments.aibank_agent_keys import (
    AgentKeyCipher,
    InMemoryAgentKeyStore,
    StoredAgent,
    identity_of,
    load_or_register_buyer,
    rotate_agent_key,
)
from agent_commerce.payments.aibank_api import AIBankError, Intent
from agent_commerce.payments.aibank_signing import AgentIdentity, generate_agent_key
from agent_commerce.payments.protocols.ap2_protocol import AP2Protocol

_SCOPE = "http://banco.test#mercatus"
_LABEL = "dashboard_buyer"


def _protocol() -> AP2Protocol:
    return AP2Protocol(Settings(mode=Mode.MOCK, protocol=Protocol.AP2, ap2_settlement=SettlementRail.AIBANK))


async def _pay(protocol: AP2Protocol, payer: str, agent: AgentIdentity, key: str) -> str:
    seller = protocol.provision_aibank_account("seller")
    authorization = await protocol.aibank.authorize(
        payer_account_id=payer,
        payee_account_id=seller.account_id,
        amount=1_000,
        idempotency_key=key,
        agent=agent,
        intent=Intent(reference="task-1", description="Text Summarizer: resumen"),
    )
    return authorization.status


def test_the_private_key_is_stored_encrypted_and_round_trips() -> None:
    cipher = AgentKeyCipher(AgentKeyCipher.generate_master_key())
    private_key = generate_agent_key()
    raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    token = cipher.encrypt(private_key)
    assert raw.hex() not in token and base64.b64encode(raw).decode() not in token
    restored = cipher.decrypt(token)
    assert restored.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()) == raw


def test_without_the_master_key_the_stored_key_is_useless() -> None:
    token = AgentKeyCipher(AgentKeyCipher.generate_master_key()).encrypt(generate_agent_key())
    with pytest.raises(ValueError, match="clave maestra"):
        AgentKeyCipher(AgentKeyCipher.generate_master_key()).decrypt(token)


def test_a_malformed_master_key_is_rejected_with_instructions() -> None:
    with pytest.raises(ValueError, match="Fernet.generate_key"):
        AgentKeyCipher("no-es-una-clave")


async def test_a_restart_reuses_the_same_agent_and_account() -> None:
    protocol, store = _protocol(), InMemoryAgentKeyStore()
    cipher = AgentKeyCipher(AgentKeyCipher.generate_master_key())
    kwargs = {"protocol": protocol, "store": store, "cipher": cipher, "scope": _SCOPE, "label": _LABEL}

    first = load_or_register_buyer(**kwargs, agent_name="Agente comprador")  # type: ignore[arg-type]
    stored = store.get(_SCOPE, _LABEL)
    assert stored is not None and stored.agent_id == first.agent.agent_id  # type: ignore[union-attr]

    # "Reinicio": nada en memoria, solo lo guardado y la clave maestra.
    again = load_or_register_buyer(**kwargs, agent_name="Agente comprador")  # type: ignore[arg-type]
    assert again.agent is not None and first.agent is not None
    assert (again.account_id, again.agent.agent_id, again.agent.key_id) == (
        first.account_id,
        first.agent.agent_id,
        first.agent.key_id,
    )
    # Y con la clave descifrada el banco acepta su firma.
    assert await _pay(protocol, again.account_id, again.agent, "after-restart") == "authorized"


async def test_rotation_saves_the_new_key_and_retires_the_old_one() -> None:
    protocol, store = _protocol(), InMemoryAgentKeyStore()
    cipher = AgentKeyCipher(AgentKeyCipher.generate_master_key())
    buyer = load_or_register_buyer(
        protocol=protocol, store=store, cipher=cipher, scope=_SCOPE, label=_LABEL, agent_name="Agente comprador"
    )
    assert buyer.agent is not None

    rotated = await rotate_agent_key(
        api=protocol.aibank, current=buyer.agent, store=store, cipher=cipher, scope=_SCOPE, label=_LABEL
    )
    assert rotated.agent_id == buyer.agent.agent_id and rotated.key_id != buyer.agent.key_id
    stored = store.get(_SCOPE, _LABEL)
    assert stored is not None and stored.key_id == rotated.key_id
    assert identity_of(stored, cipher).key_id == rotated.key_id

    assert await _pay(protocol, buyer.account_id, rotated, "with-new-key") == "authorized"
    with pytest.raises(AIBankError, match="agent_signature_invalid"):
        await _pay(protocol, buyer.account_id, buyer.agent, "with-old-key")


async def test_if_retiring_the_old_key_fails_the_new_one_is_already_saved() -> None:
    """El orden importa: guardar la nueva ANTES de retirar la vieja. Si el
    retiro falla, lo guardado sigue siendo una clave que el banco acepta."""
    protocol, store = _protocol(), InMemoryAgentKeyStore()
    cipher = AgentKeyCipher(AgentKeyCipher.generate_master_key())
    buyer = load_or_register_buyer(
        protocol=protocol, store=store, cipher=cipher, scope=_SCOPE, label=_LABEL, agent_name="Agente comprador"
    )
    assert buyer.agent is not None
    api = protocol.aibank

    async def failing_retire(agent_id: str, key_id: str) -> None:
        raise AIBankError("service_unavailable")

    api.retire_agent_key = failing_retire  # type: ignore[method-assign]
    with pytest.raises(AIBankError):
        await rotate_agent_key(api=api, current=buyer.agent, store=store, cipher=cipher, scope=_SCOPE, label=_LABEL)

    stored = store.get(_SCOPE, _LABEL)
    assert stored is not None and stored.key_id != buyer.agent.key_id
    assert await _pay(protocol, buyer.account_id, identity_of(stored, cipher), "saved-key") == "authorized"


async def test_rotating_an_agent_that_is_not_stored_is_refused() -> None:
    protocol, store = _protocol(), InMemoryAgentKeyStore()
    cipher = AgentKeyCipher(AgentKeyCipher.generate_master_key())
    stranger = protocol.provision_aibank_agent("Agente no guardado")
    store.save(
        StoredAgent(
            scope=_SCOPE,
            label=_LABEL,
            agent_id="agt_" + "0" * 32,
            agent_name="otro",
            key_id="key_" + "0" * 32,
            encrypted_private_key=cipher.encrypt(generate_agent_key()),
        )
    )
    with pytest.raises(ValueError, match="no hay un agente guardado"):
        await rotate_agent_key(api=protocol.aibank, current=stranger, store=store, cipher=cipher, scope=_SCOPE, label=_LABEL)
    # Y no quedó ninguna clave huérfana registrada en el banco.
    assert len((await protocol.aibank.get_agent(stranger.agent_id)).keys) == 1
