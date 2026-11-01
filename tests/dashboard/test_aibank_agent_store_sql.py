"""`SqlAibankAgentStore`: guarda la clave del agente tal como llega (ya
cifrada) y la recupera por banco + etiqueta."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from agent_commerce.dashboard.adapters.sql_aibank_agent_store import SqlAibankAgentStore
from agent_commerce.payments.aibank_agent_keys import StoredAgent

_AGENT = StoredAgent(
    scope="http://localhost:8081#mercatus_sandbox",
    label="dashboard_buyer",
    agent_id="agt_" + "a" * 32,
    agent_name="Agente comprador del dashboard de Mercatus",
    key_id="key_" + "b" * 32,
    encrypted_private_key="gAAAAA-texto-cifrado",
    account_id="acc_" + "c" * 32,
)


def test_save_then_get_returns_the_same_agent(db_session: Session) -> None:
    store = SqlAibankAgentStore(db_session)
    assert store.get(_AGENT.scope, _AGENT.label) is None
    store.save(_AGENT)
    assert store.get(_AGENT.scope, _AGENT.label) == _AGENT


def test_saving_again_replaces_the_key_without_duplicating(db_session: Session) -> None:
    store = SqlAibankAgentStore(db_session)
    store.save(_AGENT)
    rotated = replace(_AGENT, key_id="key_" + "d" * 32, encrypted_private_key="gAAAAA-otra")
    store.save(rotated)
    assert store.get(_AGENT.scope, _AGENT.label) == rotated


def test_the_same_label_is_another_agent_in_another_bank(db_session: Session) -> None:
    store = SqlAibankAgentStore(db_session)
    store.save(_AGENT)
    production = replace(_AGENT, scope="https://api.aerarium.pe#mercatus", agent_id="agt_" + "e" * 32)
    store.save(production)
    assert store.get(_AGENT.scope, _AGENT.label) == _AGENT
    assert store.get(production.scope, production.label) == production
