from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from agent_commerce.dashboard.adapters.sql_agent_store import SqlAgentStore
from agent_commerce.db.models import UserModel


def _make_user(db_session: Session, username: str = "alice") -> UserModel:
    user = UserModel(username=username, hashed_password="hashed")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_create_list_get_delete_agent(db_session: Session) -> None:
    user = _make_user(db_session)
    store = SqlAgentStore(db_session)
    assert store.list_agents(owner_user_id=user.id) == []

    created = store.create_agent(
        owner_user_id=user.id,
        name="Research Assistant",
        instructions="Be concise.",
        llm_model="qwen2.5-7b-instruct",
        protocol="x402",
        spend_limit_usd=Decimal("1.00"),
    )
    assert created.id is not None
    assert created.name == "Research Assistant"
    assert created.spend_limit_usd == Decimal("1.00")

    fetched = store.get_agent(created.id)
    assert fetched is not None
    assert fetched.name == "Research Assistant"

    assert [a.id for a in store.list_agents(owner_user_id=user.id)] == [created.id]
    assert store.get_agent(999999) is None

    assert store.delete_agent(created.id) is True
    assert store.list_agents(owner_user_id=user.id) == []
    assert store.delete_agent(created.id) is False


def test_list_agents_is_scoped_to_owner(db_session: Session) -> None:
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    store = SqlAgentStore(db_session)

    store.create_agent(
        owner_user_id=alice.id,
        name="Alice's agent",
        instructions="",
        llm_model="m",
        protocol="x402",
        spend_limit_usd=None,
    )
    store.create_agent(
        owner_user_id=bob.id,
        name="Bob's agent",
        instructions="",
        llm_model="m",
        protocol="ap2",
        spend_limit_usd=None,
    )

    alice_agents = store.list_agents(owner_user_id=alice.id)
    assert [a.name for a in alice_agents] == ["Alice's agent"]


def test_conversations_and_messages(db_session: Session) -> None:
    user = _make_user(db_session)
    store = SqlAgentStore(db_session)
    agent = store.create_agent(
        owner_user_id=user.id,
        name="Agent",
        instructions="",
        llm_model="m",
        protocol="x402",
        spend_limit_usd=None,
    )

    assert store.list_conversations(agent.id) == []
    conversation = store.create_conversation(agent_id=agent.id, title="First chat")
    assert conversation.agent_id == agent.id

    fetched = store.get_conversation(conversation.id)
    assert fetched is not None
    assert fetched.title == "First chat"
    assert store.get_conversation(999999) is None
    assert [c.id for c in store.list_conversations(agent.id)] == [conversation.id]

    assert store.list_messages(conversation.id) == []
    user_message = store.add_message(
        conversation_id=conversation.id, role="user", content="Summarize this text"
    )
    assert user_message.trace is None

    trace = [
        {"turn": 1, "thought": "search", "action": "search_catalog", "action_input": {}, "observation": {}}
    ]
    agent_message = store.add_message(
        conversation_id=conversation.id,
        role="agent",
        content="Here's the summary",
        trace=trace,
        total_spent_usd=Decimal("0.001"),
    )
    assert agent_message.trace == trace
    assert agent_message.total_spent_usd == Decimal("0.001")

    messages = store.list_messages(conversation.id)
    assert [m.id for m in messages] == [user_message.id, agent_message.id]


def test_deleting_agent_cascades_to_conversations_and_messages(db_session: Session) -> None:
    from agent_commerce.db.models import AgentConversationModel, AgentMessageModel

    user = _make_user(db_session)
    store = SqlAgentStore(db_session)
    agent = store.create_agent(
        owner_user_id=user.id,
        name="Agent",
        instructions="",
        llm_model="m",
        protocol="x402",
        spend_limit_usd=None,
    )
    conversation = store.create_conversation(agent_id=agent.id, title="chat")
    store.add_message(conversation_id=conversation.id, role="user", content="hi")

    assert store.delete_agent(agent.id) is True

    assert db_session.get(AgentConversationModel, conversation.id) is None
    remaining_messages = (
        db_session.query(AgentMessageModel)
        .filter(AgentMessageModel.conversation_id == conversation.id)
        .all()
    )
    assert remaining_messages == []
