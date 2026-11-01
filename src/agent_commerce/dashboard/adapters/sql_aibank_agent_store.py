"""`AgentKeyStore` respaldado por Postgres (tabla `aibank_agent_keys`).

Guarda la clave privada de cada agente tal como llega: ya cifrada por
`AgentKeyCipher`. Este adaptador nunca ve la clave en claro."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.db.models import AibankAgentKeyModel
from agent_commerce.payments.aibank_agent_keys import StoredAgent


class SqlAibankAgentStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _find(self, scope: str, label: str) -> AibankAgentKeyModel | None:
        return self._db.scalars(
            select(AibankAgentKeyModel).where(AibankAgentKeyModel.scope == scope, AibankAgentKeyModel.label == label)
        ).first()

    def get(self, scope: str, label: str) -> StoredAgent | None:
        model = self._find(scope, label)
        if model is None:
            return None
        return StoredAgent(
            scope=model.scope,
            label=model.label,
            agent_id=model.agent_id,
            agent_name=model.agent_name,
            key_id=model.key_id,
            encrypted_private_key=model.encrypted_private_key,
            account_id=model.account_id,
        )

    def save(self, agent: StoredAgent) -> None:
        model = self._find(agent.scope, agent.label)
        if model is None:
            model = AibankAgentKeyModel(scope=agent.scope, label=agent.label)
            self._db.add(model)
        model.agent_id = agent.agent_id
        model.agent_name = agent.agent_name
        model.key_id = agent.key_id
        model.encrypted_private_key = agent.encrypted_private_key
        model.account_id = agent.account_id
        self._db.commit()
