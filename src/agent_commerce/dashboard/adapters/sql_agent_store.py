"""`AgentStore` respaldado por Postgres."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_commerce.db.models import AgentConversationModel, AgentMessageModel, AgentModel

from ..ports import Agent, AgentConversation, AgentMessage


def _to_agent(model: AgentModel) -> Agent:
    return Agent(
        id=model.id,
        owner_user_id=model.owner_user_id,
        name=model.name,
        instructions=model.instructions,
        llm_model=model.llm_model,
        protocol=model.protocol,
        spend_limit_usd=model.spend_limit_usd,
        created_at=model.created_at,
    )


def _to_conversation(model: AgentConversationModel) -> AgentConversation:
    return AgentConversation(
        id=model.id, agent_id=model.agent_id, title=model.title, created_at=model.created_at
    )


def _to_message(model: AgentMessageModel) -> AgentMessage:
    return AgentMessage(
        id=model.id,
        conversation_id=model.conversation_id,
        role=model.role,
        content=model.content,
        trace=model.trace,
        total_spent_usd=model.total_spent_usd,
        created_at=model.created_at,
    )


class SqlAgentStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_agent(
        self,
        *,
        owner_user_id: int,
        name: str,
        instructions: str,
        llm_model: str,
        protocol: str,
        spend_limit_usd: Decimal | None,
    ) -> Agent:
        model = AgentModel(
            owner_user_id=owner_user_id,
            name=name,
            instructions=instructions,
            llm_model=llm_model,
            protocol=protocol,
            spend_limit_usd=spend_limit_usd,
        )
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return _to_agent(model)

    def list_agents(self, *, owner_user_id: int) -> list[Agent]:
        stmt = (
            select(AgentModel)
            .where(AgentModel.owner_user_id == owner_user_id)
            .order_by(AgentModel.created_at.desc())
        )
        return [_to_agent(m) for m in self._db.execute(stmt).scalars().all()]

    def get_agent(self, agent_id: int) -> Agent | None:
        model = self._db.get(AgentModel, agent_id)
        return _to_agent(model) if model is not None else None

    def delete_agent(self, agent_id: int) -> bool:
        model = self._db.get(AgentModel, agent_id)
        if model is None:
            return False
        self._db.delete(model)
        self._db.commit()
        return True

    def create_conversation(self, *, agent_id: int, title: str) -> AgentConversation:
        model = AgentConversationModel(agent_id=agent_id, title=title)
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return _to_conversation(model)

    def list_conversations(self, agent_id: int) -> list[AgentConversation]:
        stmt = (
            select(AgentConversationModel)
            .where(AgentConversationModel.agent_id == agent_id)
            .order_by(AgentConversationModel.created_at.desc())
        )
        return [_to_conversation(m) for m in self._db.execute(stmt).scalars().all()]

    def get_conversation(self, conversation_id: int) -> AgentConversation | None:
        model = self._db.get(AgentConversationModel, conversation_id)
        return _to_conversation(model) if model is not None else None

    def add_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        trace: list[dict[str, Any]] | None = None,
        total_spent_usd: Decimal | None = None,
    ) -> AgentMessage:
        model = AgentMessageModel(
            conversation_id=conversation_id,
            role=role,
            content=content,
            trace=trace,
            total_spent_usd=total_spent_usd,
        )
        self._db.add(model)
        self._db.commit()
        self._db.refresh(model)
        return _to_message(model)

    def list_messages(self, conversation_id: int) -> list[AgentMessage]:
        stmt = (
            select(AgentMessageModel)
            .where(AgentMessageModel.conversation_id == conversation_id)
            .order_by(AgentMessageModel.created_at.asc())
        )
        return [_to_message(m) for m in self._db.execute(stmt).scalars().all()]
