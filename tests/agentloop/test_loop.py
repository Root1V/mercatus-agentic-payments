from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from agent_commerce.agentloop.loop import AgentLoop, AgentLoopError, MaxTurnsExceededError
from agent_commerce.catalog.models import ServiceListing
from agent_commerce.client.paying_agent import ServiceCallResult


class FakeLLM:
    """Devuelve las respuestas dadas, una por cada llamada a `chat_completion`."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def chat_completion(self, *, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls.append(messages)
        content = next(self._responses)
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class FakePayingAgent:
    def __init__(
        self,
        listings: list[ServiceListing],
        *,
        call_results: dict[str, ServiceCallResult] | None = None,
        call_error: Exception | None = None,
    ) -> None:
        self._listings = listings
        self._call_results = call_results or {}
        self._call_error = call_error
        self.call_service_calls: list[tuple[str, dict[str, Any] | None]] = []

    async def discover(self, query: str) -> list[ServiceListing]:
        q = query.lower()
        return [
            listing
            for listing in self._listings
            if q in listing.name.lower()
            or q in listing.description.lower()
            or any(q in tag.lower() for tag in listing.capability_tags)
        ]

    async def call_service(
        self, capability: str, payload: dict[str, Any] | None = None
    ) -> ServiceCallResult:
        self.call_service_calls.append((capability, payload))
        if self._call_error is not None:
            raise self._call_error
        return self._call_results[capability]


def _listing(**overrides: Any) -> ServiceListing:
    defaults: dict[str, Any] = {
        "id": "text-summarizer",
        "name": "Text Summarizer",
        "description": "Resume un texto a oraciones clave",
        "method": "POST",
        "url": "http://127.0.0.1:8901/summarize",
        "price_usd": "$0.001",
        "capability_tags": ["summarize", "text"],
        "protocols": ["x402"],
        "provider_name": "agent_commerce demo",
    }
    defaults.update(overrides)
    return ServiceListing.model_validate(defaults)


def _final_answer_json(answer: str) -> str:
    return json.dumps({"thought": "done", "action": "final_answer", "action_input": {"answer": answer}})


@pytest.mark.asyncio
async def test_final_answer_on_first_turn() -> None:
    llm = FakeLLM([_final_answer_json("42")])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([]), model="test-model")

    result = await loop.run("What is the answer?")

    assert result.answer == "42"
    assert result.turns_used == 1
    assert result.total_spent_usd == Decimal(0)
    assert len(result.trace) == 1
    assert result.trace[0].action == "final_answer"


@pytest.mark.asyncio
async def test_search_catalog_then_final_answer() -> None:
    listing = _listing()
    search_json = json.dumps(
        {"thought": "let's look", "action": "search_catalog", "action_input": {"query": "summarize"}}
    )
    llm = FakeLLM([search_json, _final_answer_json("found it")])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([listing]), model="test-model")

    result = await loop.run("Summarize this for me")

    assert result.answer == "found it"
    assert result.turns_used == 2
    assert result.trace[0].observation["results"][0]["id"] == "text-summarizer"
    # La observación del turno 1 debe llegarle al modelo en el turno 2.
    second_call_messages = llm.calls[1]
    assert any("text-summarizer" in m["content"] for m in second_call_messages)


@pytest.mark.asyncio
async def test_call_service_success_accumulates_spend() -> None:
    listing = _listing()
    call_json = json.dumps(
        {
            "thought": "pay for it",
            "action": "call_service",
            "action_input": {"capability": "summarize", "payload": {"text": "hello"}},
        }
    )
    llm = FakeLLM([call_json, _final_answer_json("summarized")])
    call_result = ServiceCallResult(
        data={"summary": "hi"}, price_paid_usd=Decimal("0.001"), receipt=None, listing=listing
    )
    paying_agent = FakePayingAgent([listing], call_results={"summarize": call_result})
    loop = AgentLoop(llm=llm, paying_agent=paying_agent, model="test-model")

    result = await loop.run("Summarize 'hello'")

    assert result.total_spent_usd == Decimal("0.001")
    assert paying_agent.call_service_calls == [("summarize", {"text": "hello"})]
    assert result.trace[0].observation["service_id"] == "text-summarizer"


@pytest.mark.asyncio
async def test_call_service_over_spend_limit_is_refused_without_calling() -> None:
    listing = _listing(price_usd="$0.01")
    call_json = json.dumps(
        {
            "thought": "pay for it",
            "action": "call_service",
            "action_input": {"capability": "summarize", "payload": {}},
        }
    )
    llm = FakeLLM([call_json, _final_answer_json("too expensive")])
    paying_agent = FakePayingAgent([listing])
    loop = AgentLoop(
        llm=llm, paying_agent=paying_agent, model="test-model", spend_limit_usd=Decimal("0.001")
    )

    result = await loop.run("Summarize this")

    assert paying_agent.call_service_calls == []
    assert "excede el límite" in result.trace[0].observation["error"]
    assert result.total_spent_usd == Decimal(0)


@pytest.mark.asyncio
async def test_call_service_failure_is_reported_as_observation_not_raised() -> None:
    listing = _listing()
    call_json = json.dumps(
        {"thought": "pay", "action": "call_service", "action_input": {"capability": "summarize"}}
    )
    llm = FakeLLM([call_json, _final_answer_json("it failed")])
    paying_agent = FakePayingAgent([listing], call_error=RuntimeError("service returned 500"))
    loop = AgentLoop(llm=llm, paying_agent=paying_agent, model="test-model")

    result = await loop.run("Summarize this")

    assert "service returned 500" in result.trace[0].observation["error"]
    assert result.total_spent_usd == Decimal(0)


@pytest.mark.asyncio
async def test_invalid_json_is_retried_once_then_succeeds() -> None:
    llm = FakeLLM(["not json at all", _final_answer_json("recovered")])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([]), model="test-model")

    result = await loop.run("hi")

    assert result.answer == "recovered"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_invalid_json_exhausts_retries_raises_agent_loop_error() -> None:
    llm = FakeLLM(["not json", "still not json"])
    loop = AgentLoop(
        llm=llm, paying_agent=FakePayingAgent([]), model="test-model", max_json_retries_per_turn=1
    )

    with pytest.raises(AgentLoopError):
        await loop.run("hi")


@pytest.mark.asyncio
async def test_max_turns_exceeded_raises() -> None:
    search_json = json.dumps(
        {"thought": "still looking", "action": "search_catalog", "action_input": {"query": "x"}}
    )
    llm = FakeLLM([search_json, search_json])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([]), model="test-model", max_turns=2)

    with pytest.raises(MaxTurnsExceededError):
        await loop.run("hi")


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed() -> None:
    fenced = "```json\n" + _final_answer_json("fenced") + "\n```"
    llm = FakeLLM([fenced])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([]), model="test-model")

    result = await loop.run("hi")

    assert result.answer == "fenced"


@pytest.mark.asyncio
async def test_extra_instructions_are_appended_to_system_prompt() -> None:
    llm = FakeLLM([_final_answer_json("done")])
    loop = AgentLoop(
        llm=llm,
        paying_agent=FakePayingAgent([]),
        model="test-model",
        extra_instructions="Always answer in pirate speak.",
    )

    await loop.run("hi")

    system_message = llm.calls[0][0]
    assert system_message["role"] == "system"
    assert "Always answer in pirate speak." in system_message["content"]
    assert "search_catalog" in system_message["content"]  # el contrato JSON sigue presente


@pytest.mark.asyncio
async def test_search_catalog_no_matches_returns_error_observation() -> None:
    search_json = json.dumps(
        {"thought": "look", "action": "search_catalog", "action_input": {"query": "nonexistent"}}
    )
    llm = FakeLLM([search_json, _final_answer_json("nothing found")])
    loop = AgentLoop(llm=llm, paying_agent=FakePayingAgent([]), model="test-model")

    result = await loop.run("hi")

    assert "No se encontró" in result.trace[0].observation["error"]
