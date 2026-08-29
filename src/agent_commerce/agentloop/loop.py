"""Loop de razonamiento del agente: contrato JSON estricto tipo ReAct.

El gateway de Prometheus (`agent_commerce.llm.client`) no soporta
function-calling nativo -- su `ChatCompletionRequest` no tiene campos
`tools`/`tool_choice` (verificado leyendo su código, ver docs/roadmap.md
RM-11). Por eso el tool-use se implementa aquí como un contrato JSON
estricto dentro del prompt: en cada turno el modelo debe responder con un
único objeto JSON (`thought`/`action`/`action_input`, patrón ReAct),
parseado a mano. Si la respuesta no es JSON válido se le da al modelo una
oportunidad de corregirlo antes de abortar (`max_json_retries_per_turn`), y
hay un límite duro de turnos (`max_turns`) para que un agente que nunca
llega a `final_answer` no corra indefinidamente.

Reusa `PayingAgent.discover`/`call_service` para pagos reales -- este
módulo no sabe nada de x402/AP2 ni de wallets, solo del puerto que ya
expone `client/paying_agent.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from x402.schemas.helpers import parse_money

if TYPE_CHECKING:
    from agent_commerce.client.paying_agent import PayingAgent
    from agent_commerce.llm.client import PrometheusLLMClient

_ACTIONS = {"search_catalog", "call_service", "final_answer"}

_SYSTEM_PROMPT = """You are an autonomous purchasing agent. You can search a paid-service \
catalog and pay to call a service when it helps answer the user's request. \
You do not have native tool calling -- you MUST respond with EXACTLY ONE JSON object \
per turn, nothing else: no markdown fences, no prose outside the JSON.

The JSON object has this shape:
{"thought": "<your reasoning, one or two sentences>", "action": "<one of: search_catalog, \
call_service, final_answer>", "action_input": {...}}

Actions:
- search_catalog: action_input = {"query": "<capability keywords>"}. Returns matching \
services (id, name, price_usd, capability_tags). Use this before call_service if you don't \
already know which service to use.
- call_service: action_input = {"capability": "<keywords matching a service from \
search_catalog>", "payload": {<JSON body for the service, or {} if none needed>}}. This \
SPENDS REAL MONEY up to the service's listed price_usd -- only call it when it's actually \
needed to answer the request.
- final_answer: action_input = {"answer": "<your final answer to the user, in plain text>"}. \
Use this as soon as you have enough information -- do not call services you don't need. Keep \
"answer" reasonably short: if a service already returned the result in an observation, refer to \
it briefly instead of copying it back character-for-character -- a very long value here is more \
likely to break the JSON you're producing.

Respond with the JSON object now."""


class AgentLoopError(Exception):
    """Error irrecuperable del loop (no confundir con una `observation` de
    error, que se reporta al modelo para que decida cómo seguir)."""


class MaxTurnsExceededError(AgentLoopError):
    """El agente no llegó a `final_answer` dentro del límite duro de turnos."""


@dataclass
class TraceStep:
    """Un paso del loop: lo que pensó, qué acción tomó y qué observó.
    Es el entregable central del panel de traza del playground (RM-15)."""

    turn: int
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: Any


@dataclass
class AgentLoopResult:
    answer: str
    trace: list[TraceStep]
    total_spent_usd: Decimal
    turns_used: int


@dataclass
class _ParsedAction:
    thought: str
    action: str
    action_input: dict[str, Any]


def _parse_action(raw_content: str) -> _ParsedAction:
    text = raw_content.strip()
    if not text:
        # Modelos "razonadores" (p. ej. gpt-oss vía llama.cpp) a veces dejan
        # `content` vacío y ponen toda su respuesta -- incluida la acción --
        # en `reasoning_content` en vez de escribirla como mensaje visible.
        # `_get_valid_action` ya usa `reasoning_content` como fallback de
        # texto, así que si igual llega vacío acá es porque el modelo no
        # escribió nada visible en absoluto -- un mensaje correctivo
        # explícito (probado a mano contra un gpt-oss real) sí logra que en
        # el siguiente intento el modelo escriba el JSON como contenido
        # visible en vez de solo razonar sobre qué haría.
        raise ValueError(
            "La respuesta vino vacía. Escribí el objeto JSON de acción como tu mensaje "
            "visible (contenido de respuesta), no solo como razonamiento interno."
        )
    # Modelos locales a veces envuelven la respuesta en fences de markdown
    # pese a la instrucción explícita de no hacerlo -- se pelan antes de
    # json.loads en vez de tratarlo como un error de formato.
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("La respuesta del modelo no es un objeto JSON")

    action = data.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"Acción desconocida: {action!r}")

    action_input = data.get("action_input")
    if not isinstance(action_input, dict):
        raise TypeError("'action_input' debe ser un objeto JSON")

    return _ParsedAction(thought=str(data.get("thought", "")), action=action, action_input=action_input)


class AgentLoop:
    """Ejecuta pensar -> actuar -> observar hasta `final_answer` o
    `max_turns`. Cada instancia sirve para una sola conversación de una sola
    vez (no reintenta ni conserva estado entre llamadas a `run`).
    """

    def __init__(
        self,
        *,
        llm: PrometheusLLMClient,
        paying_agent: PayingAgent,
        model: str,
        max_turns: int = 8,
        max_json_retries_per_turn: int = 2,
        spend_limit_usd: Decimal | None = None,
        extra_instructions: str = "",
    ) -> None:
        self._llm = llm
        self._paying_agent = paying_agent
        self._model = model
        self._max_turns = max_turns
        self._max_json_retries_per_turn = max_json_retries_per_turn
        self._spend_limit_usd = spend_limit_usd
        self._spent_usd = Decimal(0)
        # Persona/instrucciones del usuario (p. ej. el "prompt" que se define
        # al crear el agente en el playground, RM-15): se agregan DESPUÉS del
        # contrato JSON fijo, nunca lo reemplazan -- si contradicen el
        # contrato, el modelo puede dejar de responder en JSON válido.
        self._system_prompt = f"{_SYSTEM_PROMPT}\n\n{extra_instructions}" if extra_instructions else _SYSTEM_PROMPT

    async def run(self, user_message: str) -> AgentLoopResult:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]
        trace: list[TraceStep] = []

        for turn in range(1, self._max_turns + 1):
            parsed = await self._get_valid_action(messages)
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "thought": parsed.thought,
                            "action": parsed.action,
                            "action_input": parsed.action_input,
                        }
                    ),
                }
            )

            if parsed.action == "final_answer":
                answer = str(parsed.action_input.get("answer", ""))
                trace.append(TraceStep(turn, parsed.thought, parsed.action, parsed.action_input, answer))
                return AgentLoopResult(
                    answer=answer,
                    trace=trace,
                    total_spent_usd=self._spent_usd,
                    turns_used=turn,
                )

            observation = await self._dispatch(parsed)
            trace.append(TraceStep(turn, parsed.thought, parsed.action, parsed.action_input, observation))
            messages.append({"role": "user", "content": f"Observation: {json.dumps(observation)}"})

        raise MaxTurnsExceededError(f"El agente no llegó a 'final_answer' en {self._max_turns} turnos")

    async def _get_valid_action(self, messages: list[dict[str, str]]) -> _ParsedAction:
        attempt_messages = list(messages)
        last_error: Exception | None = None
        for _ in range(self._max_json_retries_per_turn + 1):
            response = await self._llm.chat_completion(model=self._model, messages=attempt_messages)
            message = response["choices"][0]["message"]
            # Modelos "razonadores" servidos por llama.cpp (p. ej. gpt-oss) a
            # veces dejan `content` vacío y ponen todo -- incluida la acción
            # final -- en `reasoning_content` (un campo propio de llama.cpp,
            # fuera del schema estándar de OpenAI). Sin este fallback, esos
            # modelos nunca producen una acción válida y agotan los
            # reintentos siempre, aunque el gateway responda 200 cada vez.
            content = message.get("content") or message.get("reasoning_content") or ""
            try:
                return _parse_action(content)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
                attempt_messages = [
                    *attempt_messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"Your last response was not a valid action JSON object ({exc}). "
                            "Respond again with ONLY the JSON object described in the system prompt."
                        ),
                    },
                ]

        raise AgentLoopError(
            f"El modelo no devolvió un JSON de acción válido tras "
            f"{self._max_json_retries_per_turn + 1} intentos: {last_error}"
        )

    async def _dispatch(self, parsed: _ParsedAction) -> Any:
        if parsed.action == "search_catalog":
            return await self._search_catalog(parsed.action_input)
        return await self._call_service(parsed.action_input)

    async def _search_catalog(self, action_input: dict[str, Any]) -> Any:
        query = str(action_input.get("query", ""))
        listings = await self._paying_agent.discover(query)
        if not listings:
            return {"error": f"No se encontró ningún servicio para '{query}'"}
        return {
            "results": [
                {
                    "id": listing.id,
                    "name": listing.name,
                    "price_usd": listing.price_usd,
                    "capability_tags": listing.capability_tags,
                }
                for listing in listings
            ]
        }

    async def _call_service(self, action_input: dict[str, Any]) -> Any:
        capability = str(action_input.get("capability", ""))
        payload = action_input.get("payload") or {}

        matches = await self._paying_agent.discover(capability)
        if not matches:
            return {"error": f"No se encontró ningún servicio para '{capability}'"}
        listing = matches[0]

        price_usd = Decimal(parse_money(listing.price_usd)["amount"])
        if self._spend_limit_usd is not None and self._spent_usd + price_usd > self._spend_limit_usd:
            return {
                "error": (
                    f"Llamar a '{listing.id}' costaría ${price_usd}, lo que excede el límite de "
                    f"gasto de ${self._spend_limit_usd} (ya gastado: ${self._spent_usd})"
                )
            }

        try:
            result = await self._paying_agent.call_service(capability, payload)
        except Exception as exc:  # noqa: BLE001 -- se reporta como observación, no debe tumbar el loop
            return {"error": f"Falló la llamada a '{listing.id}': {exc}"}

        if result.price_paid_usd is not None:
            self._spent_usd += result.price_paid_usd

        return {
            "service_id": result.listing.id,
            "price_paid_usd": str(result.price_paid_usd) if result.price_paid_usd is not None else None,
            "settlement_id": result.receipt.settlement_id if result.receipt else None,
            "data": result.data,
        }
