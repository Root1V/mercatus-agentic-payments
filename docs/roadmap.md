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
**Estado:** ✅ Hecho

`payments/wallets/circle_wallet.py`: adaptador opcional (`agent-commerce[circle]`), import
perezoso. La forma de la API se verificó primero instalando el extra e inspeccionando el código
fuente real de `circle-developer-controlled-wallets` 9.6.0 (no hace falta credenciales para eso,
solo el paquete): se encontraron y corrigieron tres suposiciones erróneas -- la clase es
`SigningApi` (no `SignatureApi`), los métodos son `sign_typed_data`/`sign_message` sin sufijo
`_for_developer` (no existe en esta versión), y el request de EIP-712 es `SignTypedDataRequest`
(no `SignTypedDataForDeveloperRequest`, que no existe). También se implementó `sign_message`
(EIP-191), que antes lanzaba `NotImplementedError`. Se descubrió además que ambos requests
exigen `entity_secret_ciphertext` -- el entity secret RSA-cifrado con la clave pública de
Circle, *distinto en cada request* (`circle_utils.generate_entity_secret_ciphertext`, ver
docstring del módulo) -- ausente en la versión anterior, que ni siquiera hubiera podido
autenticar una llamada real.

Verificado con tests (`tests/payments/wallets/test_circle_wallet.py`) que construyen instancias
reales de los modelos pydantic del SDK (`EOAWallet`, `SignatureResponse`, etc., no dobles
sueltos) y mockean solo las llamadas de red -- si el SDK real cambia de forma, estos tests rompen
en vez de pasar en silencio.

Después, con credenciales sandbox reales que el usuario cargó en su propio `.env`: se generó y
registró un entity secret, se creó un wallet set y dos wallets developer-controlled (comprador y
vendedor) en Base Sepolia vía la API real de Circle, y se probó `CircleWalletSigner` completo
contra esa cuenta viva -- `.address`, `sign_typed_data` (EIP-712) y `sign_message` (EIP-191)
devolvieron firmas ECDSA válidas de 65 bytes cada una. Sin fondos reales de por medio (sandbox),
pero es una prueba de extremo a extremo real, no solo contra tipos del SDK.

Incidente durante la verificación: al registrar el entity secret, un filtro de salida mal armado
dejó que el valor del secret se imprimiera igual -- quedó expuesto en la conversación (privada,
nunca publicada). Como no hay endpoint de API para rotarlo (solo vía Circle Console, confirmado
inspeccionando el SDK), se le recomendó al usuario rotarlo ahí cuando pueda; rotar no invalida las
wallets ya creadas. El archivo de recuperación de Circle y una copia local del entity secret
quedaron en `secrets/` (agregado a `.gitignore`, nunca se commitea).

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
**Estado:** ✅ Hecho

Tablas `AgentModel`/`AgentConversationModel`/`AgentMessageModel` (`db/models.py`) + migración
Alembic `0002_agent_playground.py`, con `ON DELETE CASCADE` real (agente → conversaciones →
mensajes) verificado en el test con la pragma `foreign_keys=ON` de SQLite explícita (si no,
SQLite ignora la cascada en silencio y solo se vería el problema en Postgres). Puerto `AgentStore`
nuevo en `dashboard/ports.py` (mismo patrón que `LedgerStore`/`CatalogStore`: un solo puerto para
las tres entidades porque siempre se usan juntas), con adaptadores `SqlAgentStore`/
`InMemoryAgentStore`. `AgentMessageModel.trace`/`total_spent_usd` son una copia de lectura del
resultado de `AgentLoop` (RM-12) para el panel de traza (RM-15) -- los pagos del agente caen en la
misma tabla `ledger_entries` de siempre (sin contabilidad duplicada); wire-up real de eso queda
para RM-14 (API del playground), que es quien construye el `AgentLoop` y llama a `LedgerStore` por
cada `call_service`, igual que ya hace `/api/test-call` hoy.

<a id="rm-14"></a>

## RM-14 — API del playground
**Estado:** ✅ Hecho

`dashboard/app.py`: `POST/GET /api/agents`, `DELETE /api/agents/{id}`, `GET
/api/agents/llm-models` (proxy a `GET /v1/models` de Prometheus, RM-11),
`POST/GET /api/agents/{id}/conversations`, `POST/GET .../messages`. Protegido con JWT como el
resto de `/api/*`, y con ownership explícito (`_get_owned_agent`/`_get_owned_conversation`): un
usuario no puede ver ni operar agentes de otro. `PrometheusLLMClient` (RM-11) se construye una
sola vez al levantar el dashboard (no por request, para reusar el caché de token) solo si
`AGENT_COMMERCE_LLM_CLIENT_ID`/`_SECRET` están configurados -- si no, los endpoints que lo
necesitan devuelven 500 explicando qué falta, el resto del dashboard sigue funcionando igual.

`POST .../messages` arma un `PayingAgent` (mismo patrón que `/api/test-call`: catálogo real
en memoria con el único servicio real disponible, `text-summarizer`, contra el vendedor que ya
levanta el dashboard) y corre un `AgentLoop` (RM-12) con `extra_instructions=agent.instructions`
(agregado a `AgentLoop` en esta fase, ver abajo) y `spend_limit_usd=agent.spend_limit_usd`. Un
`AgentLoopError` (turnos agotados, JSON inválido tras reintentos) se persiste como mensaje del
agente con el detalle del error -- nunca un 500 genérico. Cada paso `call_service` exitoso de la
traza se registra en `ledger_entries` vía `LedgerStore` (RM-13), igual que ya hace
`/api/test-call`. Memoria de conversación: los turnos previos se aplanan a texto plano y se
anteponen al mensaje nuevo (`_build_prompt_with_history`) -- `AgentLoop.run()` sigue razonando
sobre un único mensaje, no se le agregó soporte de historial estructurado (fuera de alcance de
esta fase).

Cambio a `agentloop/loop.py` (RM-12) necesario para que esto funcione bien: `AgentLoop` ahora
acepta `extra_instructions: str = ""`, agregado DESPUÉS del contrato JSON fijo del system prompt
-- así el "prompt" que se define al crear el agente (RM-15) es una persona/instrucción adicional,
nunca reemplaza el contrato ReAct.

10 tests nuevos (`tests/dashboard/test_agents_api.py`) contra un mock real del auth-service/
gateway de Prometheus levantado como servidor `uvicorn` (mismo patrón que los vendedores x402/AP2
de `test_dashboard_app.py`) -- ejercita el `PrometheusLLMClient` real de punta a punta, sin dobles
en proceso. Más 1 test nuevo en `tests/agentloop/test_loop.py` para `extra_instructions`.

<a id="rm-15"></a>

## RM-15 — Frontend del playground
**Estado:** ✅ Hecho

`pages/AgentPlaygroundPage.tsx` (ruta `/agentes`): panel de agentes (crear con nombre,
prompt/instrucciones, modelo -- `Select` poblado desde `GET /api/agents/llm-models`, o un
`Input` de texto libre si Prometheus no está configurado, el 500 se degrada con gracia --
protocolo, límite de gasto; listar; borrar) + chat con historial persistido (`useMessages`) y
composer. Cada mensaje del agente muestra su `TraceStep[]` (RM-12/13) en
`components/dashboard/TraceStepView.tsx`: un `<details>` nativo por turno (sin agregar un
componente Accordion nuevo) con el pensamiento, y una vista dedicada por tipo de observación --
resultados de `search_catalog`, recibo de pago (servicio/monto/ID de liquidación con
`CopyButton`) de `call_service`, o el error si la acción falló -- más el total gastado de la
respuesta. Sigue los mismos patrones ya establecidos del dashboard (`api/`, `hooks/` con
TanStack Query, primitivos de `components/ui/`, `ProtocolBadge`) sin introducir ninguno nuevo.

Bug encontrado y corregido durante la verificación manual en navegador: la card de cada agente
tenía un `<button>` de borrar anidado dentro del `<button>` de selección -- HTML inválido que
React reporta como error de hidratación y rompe el manejo de eventos. Se resolvió separando
ambos botones como hermanos dentro de un `<div className="relative">`, con el de borrar
posicionado en la esquina. También se encontró que `useLlmModels()` (que falla con 500 cuando
Prometheus no está configurado, el caso normal en este sandbox) se quedaba con `fetchStatus:
"paused"` indefinidamente en vez de asentarse en `isError` -- el retry por defecto de TanStack
Query interactúa mal con la detección de conectividad del navegador de este entorno. Se fijó
`retry: false` en ese hook (correcto de todos modos: un 500 de configuración faltante nunca se
arregla reintentando).

Verificado de punta a punta en el navegador contra el backend real (SQLite local, sin Prometheus
configurado): crear agente con fallback de modelo manual, iniciar conversación, enviar mensaje y
ver el error 500 mostrado sin romper la UI, borrar agente. El flujo completo con un LLM real
(respuesta exitosa, `call_service` pagando de verdad) no se pudo probar en este sandbox por no
tener Prometheus corriendo -- mismo límite que RM-11.

<a id="rm-16"></a>

## RM-16 — Playground: producción
**Estado:** ⬜ Backlog

Streaming SSE (pospuesto del MVP), manejo visible de fallos del gateway (nunca un 500 genérico),
documentar en el README cómo levantar Prometheus sin chocar puertos y registrar `agent_commerce`
como cliente OAuth2.

<a id="rm-17"></a>

## RM-17 — Configurar LLM desde el dashboard
**Estado:** ✅ Hecho

Motivación: RM-11/RM-14 conectaban Prometheus solo por variables de entorno del servidor
(`AGENT_COMMERCE_LLM_*`). En la práctica, quien administra el dashboard no siempre tiene acceso al
`.env` del servidor, y quien administra Prometheus es quien genera el `client_id`/`client_secret`
(vía `POST /admin/clients` de su auth-service) recién cuando se lo pide -- hacía falta poder cargar
esa conexión desde la propia UI, en caliente, sin reiniciar el proceso.

Tabla `LlmSettingsModel` (fila única, `id=1`: `auth_base_url`, `gateway_base_url`, `client_id`,
`client_secret`, `allowed_models`) + migración `0003_llm_settings.py`. Puerto `LlmSettingsStore`
nuevo en `dashboard/ports.py` (mismo patrón que los demás), adaptadores `SqlLlmSettingsStore`/
`InMemoryLlmSettingsStore`. Endpoints `GET`/`PUT /api/admin/llm-settings` -- el `GET` nunca
devuelve `client_secret` (solo `has_secret: bool`), el `PUT` con `client_secret` omitido conserva
el que ya estaba guardado (para poder editar el resto sin re-tipearlo).

`dashboard/app.py` resuelve el `PrometheusLLMClient` de forma perezosa por request
(`_get_llm_client(db)`), cacheado mientras la configuración efectiva (fila de `llm_settings` si
existe, si no `Settings.llm_*` de entorno como fallback) no cambie -- así una edición desde
`PUT /api/admin/llm-settings` toma efecto en el siguiente request sin reiniciar el dashboard, pero
mientras no cambie se reusa la misma conexión (y su caché de token OAuth2, RM-11). Deliberadamente
NO se lee la DB al construir la app: hacerlo así rompía el mecanismo de tests que reemplazan
`Depends(get_db)` después de construir la app (`tests/dashboard/conftest.py`) -- se detectó porque
los 18 tests de `test_agents_api.py`/`test_dashboard_app.py` empezaron a fallar con un error de
conexión a la Postgres real por defecto.

`GET /api/agents/llm-models` (RM-14) ahora filtra por `allowed_models` cuando hay alguno
configurado ("los modelos que se contrataron"); `?include_all=true` devuelve la lista sin filtrar,
usado solo por el propio diálogo de configuración para elegir cuáles habilitar.

`frontend/src/pages/AgentPlaygroundPage.tsx`: botón de engranaje junto a "Crear" abre
`LlmSettingsDialog` (URLs, client ID, client secret -- placeholder "dejar vacío para no
cambiarlo" una vez configurado --, y modelos habilitados como texto separado por coma, con la
lista real disponible mostrada abajo una vez que la conexión ya funciona). El sub-componente del
formulario se remonta por `key={settings.updated_at}` para siempre arrancar con los valores reales
guardados, no con lo que quedó de una edición anterior.

Verificado de punta a punta en el navegador: con un mock local del auth-service/gateway (dos
modelos), se configuró la conexión desde el diálogo (sin ninguna variable de entorno del lado del
dashboard), apareció la lista de modelos disponibles, se restringió a uno solo, y el selector de
modelo del diálogo "Nuevo agente" mostró exactamente ese único modelo -- confirmando el filtro de
`allowed_models` en vivo. 4 tests del adaptador SQL + 5 tests de la API nuevos (mock de
auth-service/gateway como servidor real, mismo patrón que RM-14).

<a id="rm-18"></a>

## RM-18 — Otros rieles de pago (tarjetas, Apple Pay, banco propio)
**Estado:** ⬜ Backlog

Hoy el framework solo liquida sobre rieles cripto (x402 directo, AP2 delegando en x402) vía el
puerto `WalletSigner` (`payments/wallets/`), diseñado específicamente alrededor de firma
EIP-712/EIP-191 (EVM). Agregar tarjetas (Visa/Mastercard), Apple Pay, o un banco propio (p. ej.
"AIBank") **no encaja como un `WalletSigner` más** -- son rieles con un modelo de
autorización/liquidación totalmente distinto (auth+capture, no una firma que habilita una
transferencia on-chain). Van a necesitar, como mínimo, un nuevo `PaymentProtocol` (o un puerto
nuevo por encima de `WalletSigner`/`PaymentProtocol`) que negocie/autorice/liquide con la forma de
cada riel -- decisión de diseño para cuando se encare esta fase, no asumida de antemano.

Por riel:

- **Visa / Mastercard**: en la práctica casi ninguna empresa integra directo contra la red -- se
  hace vía un procesador/adquirente (Stripe, Adyen, etc.) o las APIs propias de cada red (Visa
  Direct, Mastercard Send, ambas orientadas a *payouts*, no exactamente al caso de "agente le paga
  a un servicio"). Antes de codear, investigar cuál de esos caminos es real para el caso de uso
  antes de elegir uno.
- **Apple Pay**: es una capa de wallet/tokenización (PassKit, Apple Pay on the Web), no un riel de
  liquidación en sí mismo -- igual necesita un procesador de pagos por detrás, más registro de
  merchant y verificación de dominio ante Apple.
- **Banco propio (AIBank u otro)**: acá el trabajo es nuestro -- diseñar y documentar el contrato
  que ese banco tendría que exponer para integrarse (siguiendo el mismo espíritu que x402/AP2 son
  contratos abiertos que cualquiera puede implementar). Como mínimo definir: modelo de auth
  (¿OAuth2 client_credentials como Prometheus? ¿mTLS? ¿API key?), endpoints de autorización/captura/
  consulta/reembolso de un pago, idempotencia, y cómo se notifica la liquidación final (webhook vs.
  polling) -- básicamente un mini-spec de protocolo de pago, no solo un adaptador de wallet.

Sin credenciales de ninguno de estos proveedores todavía -- como con Circle (RM-06) y Prometheus
(RM-11), cualquier verificación real de este trabajo va a necesitar que el usuario provea sus
propias credenciales de sandbox y autorice cada paso explícitamente.

<a id="rm-19"></a>

## RM-19 — Configurar wallet del comprador desde el dashboard
**Estado:** ✅ Hecho

Motivación: RM-06 dejó `CircleWalletSigner` verificado, pero elegir el backend de wallet
(`local`/`circle`) seguía siendo solo por `AGENT_COMMERCE_WALLET_BACKEND` y las credenciales de
Circle en el `.env` del servidor -- para poder probar el comprador contra una wallet Circle real
desde el propio dashboard hacía falta poder cargar esa configuración desde la UI, en caliente, sin
tocar el entorno del proceso (mismo problema que resolvió RM-17 para el LLM).

Tabla `WalletSettingsModel` (fila única, `id=1`: `backend`, `circle_api_key`,
`circle_entity_secret`, `circle_wallet_id`) + migración `0004_wallet_settings.py`. Puerto
`WalletSettingsStore` nuevo en `dashboard/ports.py` (mismo patrón que `LlmSettingsStore`),
adaptadores `SqlWalletSettingsStore`/`InMemoryWalletSettingsStore`. Endpoints `GET`/
`PUT /api/admin/wallet-settings` -- el `GET` nunca devuelve `circle_api_key` ni
`circle_entity_secret` (solo `has_circle_api_key`/`has_circle_entity_secret: bool`), el `PUT` con
cualquiera de los dos omitido conserva el que ya estaba guardado.

`dashboard/app.py` resuelve el `WalletSigner` del **comprador** de forma perezosa por request
(`_get_buyer_signer(db)`), cacheado mientras la configuración efectiva no cambie -- mismo mecanismo
de "holder" que `_get_llm_client` (RM-17). El wallet del **vendedor** se mantiene estático: cada
protocolo ya corre su propio servidor FastAPI (`uvicorn.Server`) con `pay_to` fijado al construir
la app, así que cambiarlo en caliente exigiría reiniciar esos servidores -- fuera de alcance de
esta feature. Si el backend `circle` está seleccionado pero falta alguna credencial,
`/api/protocols` degrada mostrando `buyer_address: null` en vez de romper todo el endpoint, y
`/api/test-call`/el playground devuelven un 500 con un mensaje explícito señalando dónde
configurarlo.

`frontend/src/pages/BuyerTestPage.tsx`: botón "Configurar wallet" junto al título abre un diálogo
(mismo patrón `LlmSettingsDialog` de RM-17) con backend local/Circle, y para Circle: API key,
entity secret y wallet ID (los dos primeros con placeholder "dejar vacío para no cambiarlo" una vez
configurados). `ProtocolCompareCard` muestra "Wallet mal configurada" en vez de una dirección
inválida cuando el backend Circle está incompleto.

**Incidente de seguridad detectado y corregido durante la implementación**: la primera versión del
formulario mostraba `circle_api_key` como texto plano (mismo trato que `client_id` de RM-17,
razonando que era un "identificador"), pero a diferencia de un `client_id` de OAuth2, el API key de
Circle autentica por sí solo -- es un secreto, no un identificador. Un screenshot tomado durante la
verificación en vivo expuso el valor real en la conversación. Se corrigió antes de terminar la
feature: mismo tratamiento que `circle_entity_secret` en todas las capas (adaptadores, serializador
de la API, formulario del frontend como campo `password` sin prellenar). Se recomendó al usuario
rotar tanto el API key como el entity secret (este último ya había tenido una exposición similar
durante RM-06) vía console.circle.com -- no hay rotación por API.

Verificado de punta a punta: 6 tests del adaptador SQL + 8 tests de la API (incluye un test central
que configura el backend `circle` solo vía la API del dashboard -- sin ninguna variable de entorno
-- y confirma que un pago x402 real en modo mock efectivamente liquida firmado por esa wallet,
mockeando únicamente las llamadas de red del SDK de Circle con firmas EIP-712/EIP-191
criptográficamente válidas). Verificado en el navegador que el diálogo enmascara correctamente
ambos secretos tras el fix.

<a id="rm-20"></a>

## RM-20 — Rebranding del dashboard a "Mercatus"
**Estado:** ✅ Hecho

El dashboard se identificaba en todos lados como "agent_commerce" (nombre técnico del repo/paquete
Python) en vez del nombre de cara al usuario, "Mercatus". El usuario no tenía un archivo de logo
propio, así que se generó un monograma simple ("M" en trazo blanco sobre un cuadrado redondeado con
degradé `--primary` → `--accent`, `#5048e5` → `#9560f0` -- los mismos tokens de color que ya usa el
resto del dashboard) como `frontend/public/favicon.svg`, y se referencia con `<img>` desde el
sidebar y la pantalla de login en vez de duplicar el ícono -- una sola fuente de verdad para el
logo.

Cambios, todos en `frontend/` (de cara al usuario, sin tocar nombres internos):
- `index.html`: `<title>` → "Mercatus · dashboard".
- `components/layout/Sidebar.tsx`: nombre → "Mercatus", ícono `Zap` de lucide reemplazado por el
  favicon.
- `pages/LoginPage.tsx`: mismo cambio de nombre + logo en la tarjeta de login.
- `pages/CatalogPage.tsx`: el valor y el placeholder por defecto de "Proveedor" al crear un listing
  pasan de "agent_commerce demo" a "Mercatus demo" (es texto de UI, no un default de negocio).

Deliberadamente NO se tocó: el nombre del paquete Python (`agent_commerce`), del repo, la clave de
`localStorage` (`agent_commerce_token`, cambiarla forzaría relogueo sin ningún beneficio), ni el
`provider_name`/`merchant_name` por defecto ("agent_commerce demo") que usan
`catalog/models.py`, `ap2_protocol.py`, `dashboard/app.py`, `db/models.py` y
`data/catalog.sample.json` -- ese es un default de negocio que viaja dentro de los mandatos AP2 y
en filas ya sembradas de la base, con un radio de impacto mayor al de un rebranding visual; se
puede revisar aparte si se quiere.

Verificado en el navegador: título de la pestaña, logo y nombre en el sidebar (autenticado) y en la
pantalla de login (sin sesión) -- build (`npm run build`) y lint (`npm run lint`) limpios.
