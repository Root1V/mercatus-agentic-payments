# agent_commerce — dashboard (frontend)

Panel interactivo para probar el framework [`agent_commerce`](../README.md): cada protocolo
de pago (x402 / AP2), cada rol (comprador / vendedor), el catálogo de servicios y el historial
de actividad. React 19 + Vite + TypeScript + Tailwind CSS v4 + TanStack Query + react-router-dom.

Ver la sección ["Dashboard interactivo"](../README.md#dashboard-interactivo) del README
principal para el flujo completo (backend + frontend, con o sin Docker).

## Desarrollo

```bash
npm install
npm run dev       # http://localhost:5173, proxy /api -> http://localhost:8000 (ver vite.config.ts)
```

Requiere que el backend (`uv run agent-commerce dashboard`) esté corriendo en `:8000` — ver el
README principal para levantarlo (Postgres + migraciones + usuario admin).

## Comandos

```bash
npm run dev       # servidor de desarrollo con HMR
npm run build     # type-check (tsc -b) + build de producción a dist/
npm run lint      # ESLint 9 (flat config) + typescript-eslint
npm run preview   # sirve el build de producción localmente
```

## Estructura

```
src/
├── api/          cliente axios + un módulo por endpoint del backend
├── types/        tipos TS que reflejan las respuestas JSON reales del backend
├── hooks/        TanStack Query envolviendo cada módulo de api/
├── lib/          cn() (clsx+tailwind-merge), protocolTheme.ts (color x402/AP2), format.ts
├── components/
│   ├── ui/       primitivos estilo shadcn escritos a mano (sin Radix)
│   ├── layout/   AppShell, Sidebar, Topbar, ProtectedRoute
│   └── dashboard/ StatCard, ProtocolBadge, LedgerTable, CatalogTable, ProtocolDonut, ...
├── pages/        una por sección del nav (Inicio, Probar comprador, Probar vendedor, ...)
└── routes/       router.tsx (react-router-dom)
```
