import {
  Activity,
  Bot,
  GitCompare,
  LayoutDashboard,
  Package,
  ShoppingCart,
  Store,
  Zap,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/", label: "Inicio", icon: LayoutDashboard, end: true },
  { to: "/comprador", label: "Probar comprador", icon: ShoppingCart },
  { to: "/vendedor", label: "Probar vendedor", icon: Store },
  { to: "/catalogo", label: "Catálogo", icon: Package },
  { to: "/comparar", label: "Comparar protocolos", icon: GitCompare },
  { to: "/actividad", label: "Actividad", icon: Activity },
  { to: "/agentes", label: "Agentes", icon: Bot },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col bg-sidebar-background text-sidebar-foreground">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent">
          <Zap className="size-5 text-white" />
        </div>
        <div>
          <p className="text-sm font-semibold leading-tight">agent_commerce</p>
          <p className="text-xs text-sidebar-foreground/60">Panel de pruebas x402 · AP2</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-active text-white"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-muted hover:text-sidebar-foreground",
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="m-3 rounded-lg bg-sidebar-muted p-3 text-xs text-sidebar-foreground/70">
        Modo mock: sin credenciales ni fondos reales. Cambiar a testnet requiere
        variables de entorno en el backend.
      </div>
    </aside>
  );
}
