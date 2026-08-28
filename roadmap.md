# Roadmap — agent_commerce

Índice de features. Detalle de cada una en [docs/roadmap.md](docs/roadmap.md).

Estado: ✅ Hecho · 🟡 Parcial · ⬜ Backlog

| Código | Feature | Estado | Descripción |
|--------|---------|--------|-------------|
| [RM-01](docs/roadmap.md#rm-01) | Núcleo x402 | ✅ Hecho | Protocolo de liquidación directa (USDC/EIP-3009), facilitator mock + modo testnet |
| [RM-02](docs/roadmap.md#rm-02) | Núcleo AP2 | ✅ Hecho | Protocolo de mandatos (Intent/Cart/Payment) de Google, liquidado vía x402 |
| [RM-03](docs/roadmap.md#rm-03) | Catálogo + agentes comprador/vendedor | ✅ Hecho | `ServiceRegistry`, `PayingAgent`, ejemplos, demo agente-a-agente |
| [RM-04](docs/roadmap.md#rm-04) | CLI | ✅ Hecho | `agent-commerce demo/call/serve-example/catalog/dashboard/create-admin` |
| [RM-05](docs/roadmap.md#rm-05) | Análisis del modelo de negocio | ✅ Hecho | `docs/business_model_analysis.md` |
| [RM-06](docs/roadmap.md#rm-06) | Wallet Circle (custodia real) | 🟡 Parcial | Implementado, sin verificar contra credenciales reales de Circle |
| [RM-07](docs/roadmap.md#rm-07) | Backend del dashboard | ✅ Hecho | FastAPI + Postgres/SQLAlchemy/Alembic + auth JWT |
| [RM-08](docs/roadmap.md#rm-08) | Frontend del dashboard | ✅ Hecho | React 19 + Vite + Tailwind + TanStack Query |
| [RM-09](docs/roadmap.md#rm-09) | Docker Compose | 🟡 Parcial | Escrito y revisado; build no se pudo ejecutar en este sandbox (sin red a registries) |
| [RM-10](docs/roadmap.md#rm-10) | Edición de catálogo + UX del recibo | ✅ Hecho | Editar/crear servicio con proveedor, botones de copiar en el recibo |
| [RM-11](docs/roadmap.md#rm-11) | Cliente LLM (Prometheus) | ✅ Hecho | OAuth2 + chat completions contra el gateway local |
| [RM-12](docs/roadmap.md#rm-12) | Loop del agente (tool-use) | ✅ Hecho | Contrato JSON tipo ReAct (sin function-calling nativo), límite de gasto |
| [RM-13](docs/roadmap.md#rm-13) | Persistencia de agentes/conversaciones | ✅ Hecho | Tablas `Agent`/`Conversation`/`Message` + migración |
| [RM-14](docs/roadmap.md#rm-14) | API del playground | ✅ Hecho | Endpoints para crear agentes, conversar, ver historial |
| [RM-15](docs/roadmap.md#rm-15) | Frontend del playground | ✅ Hecho | Chat + panel de traza (pensamiento, tool, pago, respuesta) |
| [RM-16](docs/roadmap.md#rm-16) | Playground: producción | ⬜ Backlog | Streaming, manejo de fallos visible, docs de despliegue de Prometheus |
