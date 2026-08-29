"""`AgentStore` en memoria -- para tests, sin Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ..ports import Agent, AgentConversation, AgentMessage


class InMemoryAgentStore:
    def __init__(self) -> None:
        self._agents: dict[int, Agent] = {}
        self._conversations: dict[int, AgentConversation] = {}
        self._messages: dict[int, list[AgentMessage]] = {}
        self._next_agent_id = 1
        self._next_conversation_id = 1
        self._next_message_id = 1

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
        agent = Agent(
            id=self._next_agent_id,
            owner_user_id=owner_user_id,
            name=name,
            instructions=instructions,
            llm_model=llm_model,
            protocol=protocol,
            spend_limit_usd=spend_limit_usd,
            created_at=datetime.now(UTC),
        )
        self._agents[agent.id] = agent
        self._next_agent_id += 1
        return agent

    def list_agents(self, *, owner_user_id: int) -> list[Agent]:
        matches = [a for a in self._agents.values() if a.owner_user_id == owner_user_id]
        return sorted(matches, key=lambda a: a.created_at, reverse=True)

    def get_agent(self, agent_id: int) -> Agent | None:
        return self._agents.get(agent_id)

    def update_agent(
        self,
        agent_id: int,
        *,
        name: str,
        instructions: str,
        llm_model: str,
        protocol: str,
        spend_limit_usd: Decimal | None,
    ) -> Agent | None:
        existing = self._agents.get(agent_id)
        if existing is None:
            return None
        updated = Agent(
            id=existing.id,
            owner_user_id=existing.owner_user_id,
            name=name,
            instructions=instructions,
            llm_model=llm_model,
            protocol=protocol,
            spend_limit_usd=spend_limit_usd,
            created_at=existing.created_at,
        )
        self._agents[agent_id] = updated
        return updated

    def delete_agent(self, agent_id: int) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def create_conversation(self, *, agent_id: int, title: str) -> AgentConversation:
        conversation = AgentConversation(
            id=self._next_conversation_id, agent_id=agent_id, title=title, created_at=datetime.now(UTC)
        )
        self._conversations[conversation.id] = conversation
        self._messages[conversation.id] = []
        self._next_conversation_id += 1
        return conversation

    def list_conversations(self, agent_id: int) -> list[AgentConversation]:
        matches = [c for c in self._conversations.values() if c.agent_id == agent_id]
        return sorted(matches, key=lambda c: c.created_at, reverse=True)

    def get_conversation(self, conversation_id: int) -> AgentConversation | None:
        return self._conversations.get(conversation_id)

    def add_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        trace: list[dict[str, Any]] | None = None,
        total_spent_usd: Decimal | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            id=self._next_message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            trace=trace,
            total_spent_usd=total_spent_usd,
            created_at=datetime.now(UTC),
        )
        self._messages.setdefault(conversation_id, []).append(message)
        self._next_message_id += 1
        return message

    def list_messages(self, conversation_id: int) -> list[AgentMessage]:
        return list(self._messages.get(conversation_id, []))
