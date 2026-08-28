# Roadmap — detalle por feature

Índice y tabla de estado en [../roadmap.md](../roadmap.md). Este documento agrega contexto breve
por feature (qué es, archivos clave, decisiones/caveats) -- no el historial completo de cada
sesión de trabajo.

<a id="rm-01"></a>

## RM-01 — Núcleo x402
**Estado:** ✅ Hecho

Adaptador del protocolo x402 (liquidación directa en USDC vía EIP-3009/HTTP 402).
`payments/protocols/x402_protocol.py` + `payments/mock_facilitator.py` (verificación EIP-712
real, liquidación simulada en memoria para modo mock). Modo testnet implementado
(`HTTPFacilitatorClient` real), no ejecutado contra fondos reales.

<a id="rm-02"></a>

## RM-02 — Núcleo AP2
**Estado:** ✅ Hecho

Adaptador del protocolo AP2 de Google (mandatos `Intent`→`Cart`→`Payment`, agnóstico al riel de
pago). `payments/protocols/ap2_protocol.py`, liquida delegando en el mismo motor x402 (como la
extensión oficial `a2a-x402`). Simplificación deliberada: transporte HTTP 402 + reintento, no el
transporte A2A oficial de Google.

<a id="rm-03"></a>

## RM-03 — Catálogo + agentes comprador/vendedor
**Estado:** ✅ Hecho

`catalog/registry.py` (`ServiceRegistry`), `client/paying_agent.py` (`PayingAgent`),
`server/monetize.py`, ejemplo `examples/seller_text_summarizer/` y
`examples/agent_to_agent_demo.py` (demo end-to-end, ambos protocolos).

<a id="rm-04"></a>

## RM-04 — CLI
**Estado:** ✅ Hecho

`agent-commerce demo|call|serve-example|catalog list|catalog seed|create-admin|dashboard`
(`cli/main.py`, Typer).

<a id="rm-05"></a>

## RM-05 — Análisis del modelo de negocio
**Estado:** ✅ Hecho

[`docs/business_model_analysis.md`](business_model_analysis.md): análisis crítico de
Circle/x402/AP2 (incentivos, riesgo de dos lados, seguridad, regulación) que motivó el diseño
sin acoplamiento a un proveedor.

<a id="rm-06"></a>

## RM-06 — Wallet Circle (custodia real)
**Estado:** 🟡 Parcial

`payments/wallets/circle_wallet.py`: adaptador opcional (`agent-commerce[circle]`), import
perezoso. El método exacto de firma EIP-712 del SDK de Circle no se pudo confirmar sin
credenciales reales -- queda documentado en el propio archivo como pendiente de verificación.

<a id="rm-07"></a>

## RM-07 — Backend del dashboard
**Estado:** ✅ Hecho

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL + JWT (`db/`, `auth/`, `dashboard/`). Puertos
`LedgerStore`/`CatalogStore` con adaptadores SQL y en memoria (mismo patrón que
`WalletSigner`/`PaymentProtocol`). 54 tests, `ruff`/`mypy` en verde.

<a id="rm-08"></a>

## RM-08 — Frontend del dashboard
**Estado:** ✅ Hecho

`frontend/`: React 19 + Vite + TypeScript + Tailwind v4 + TanStack Query + react-router-dom +
axios + lucide-react. 6 páginas (Inicio, Probar comprador/vendedor, Catálogo, Comparar
protocolos, Actividad) + login JWT. Verificado en navegador de punta a punta con ambos
protocolos.

<a id="rm-09"></a>

## RM-09 — Docker Compose
**Estado:** 🟡 Parcial

`Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `docker/api-entrypoint.sh` escritos y
revisados a mano (rutas, extras de `uv`, permisos). `docker compose build` no se pudo ejecutar en
el sandbox de la sesión que lo creó (sin salida de red hacia Docker Hub/ghcr.io, confirmado con
varios intentos). Pendiente: correr `docker compose up --build` en un entorno con red normal.

<a id="rm-10"></a>

## RM-10 — Edición de catálogo + UX del recibo
**Estado:** ✅ Hecho

`PUT /api/catalog/{id}` + `CatalogStore.update()`; botón editar en `CatalogTable`; campo
"Proveedor" en el formulario de alta/edición; `components/ui/copy-button.tsx` reutilizable en
los IDs del recibo de pago (`BuyerTestPage`).

<a id="rm-11"></a>

## RM-11 — Cliente LLM (Prometheus)
**Estado:** ✅ Hecho

`llm/client.py` (`PrometheusLLMClient`): OAuth2 `client_credentials` contra
`POST {auth_base_url}/oauth2/token` del `auth-service` de Prometheus (`edge-ai-inference`,
puerto 9000 por defecto) + `POST /v1/chat/completions` y `GET /v1/models` contra su gateway.
Contrato verificado leyendo el código fuente real de Prometheus (no asumido): form-encoded en
`/oauth2/token`, `expires_in` depende del rol del client_id (300s para el rol "app"), errores de
auth en shape RFC 6749 §5.2, errores del gateway en RFC 9457 Problem Details (no el
`{"error": {...}}` de OpenAI). El token se cachea en memoria y se refresca automáticamente antes
de expirar (margen configurable), nunca solo en el fetch inicial. URL/modelo/credenciales 100%
configurables vía `Settings` (`AGENT_COMMERCE_LLM_*`) -- el puerto convencional del gateway (8000)
choca con el del propio dashboard, por eso el default de `llm_gateway_base_url` es 8001. Confirmado
que el gateway de Prometheus no soporta `tools`/`tool_choice` (los descarta en silencio): el
tool-use de RM-12 no puede delegar en function-calling nativo. Tests con `httpx.MockTransport`
(sin red real): fetch/caché/refresco de token, error de auth, error RFC 9457 del gateway,
`list_models` sin auth.

<a id="rm-12"></a>

## RM-12 — Loop del agente (tool-use)
**Estado:** ✅ Hecho

`agentloop/loop.py` (`AgentLoop`): el gateway de Prometheus **no soporta function-calling nativo**
(confirmado en RM-11 leyendo su código) -- tool-use vía contrato JSON estricto en el prompt
(patrón ReAct: `thought`/`action`/`action_input`), parseado a mano en `_parse_action` (tolera
fences de markdown que algunos modelos locales agregan pese a la instrucción de no hacerlo).
Reintento de hasta `max_json_retries_per_turn` veces si el modelo no devuelve JSON válido, y
límite duro de `max_turns` (`MaxTurnsExceededError` si nunca llega a `final_answer`). Tres
acciones: `search_catalog` (via `PayingAgent.discover`), `call_service` (via
`PayingAgent.call_service`, pagos reales) y `final_answer`. Límite de gasto opcional
(`spend_limit_usd`, nuevo -- no existía en el framework): antes de pagar, se calcula el precio del
listing con `x402.schemas.helpers.parse_money` y si excedería el límite se rechaza la acción como
una `observation` de error (el modelo la ve y puede responder sin pagar), sin llamar a
`call_service`. Cualquier falla real de la llamada (servicio caído, HTTP 4xx/5xx) también se
reporta como `observation`, nunca tumba el loop. Cada paso queda en `TraceStep` -- es el
entregable central del panel de traza del playground (RM-15). 10 tests con dobles simples de
`PrometheusLLMClient`/`PayingAgent` (sin red, sin LLM real).

<a id="rm-13"></a>

## RM-13 — Persistencia de agentes/conversaciones
**Estado:** ⬜ Backlog

Tablas `AgentModel`/`AgentConversationModel`/`AgentMessageModel` + migración Alembic. Los pagos
del agente caen en la misma tabla `ledger_entries` de siempre (sin contabilidad duplicada).

<a id="rm-14"></a>

## RM-14 — API del playground
**Estado:** ⬜ Backlog

`POST /api/agents`, `GET /api/agents`, `GET /api/agents/llm-models` (proxy a
`GET /v1/models` de Prometheus), `POST .../conversations`, `POST .../messages`. Protegido con
JWT como el resto de `/api/*`.

<a id="rm-15"></a>

## RM-15 — Frontend del playground
**Estado:** ⬜ Backlog

`pages/PlaygroundPage.tsx`: crear agente (nombre, prompt, modelo, protocolo, límite de gasto) +
chat con panel de traza expandible por turno (pensamiento → tool buscada → recibo de pago →
resultado → respuesta final). La traza es el entregable central del pedido del usuario.

<a id="rm-16"></a>

## RM-16 — Playground: producción
**Estado:** ⬜ Backlog

Streaming SSE (pospuesto del MVP), manejo visible de fallos del gateway (nunca un 500 genérico),
documentar en el README cómo levantar Prometheus sin chocar puertos y registrar `agent_commerce`
como cliente OAuth2.
