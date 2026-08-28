import { Link } from "react-router-dom";
import { Activity, CheckCircle2, DollarSign, GitCompare, Package, ShoppingCart, Store } from "lucide-react";
import { useStats } from "@/hooks/useStats";
import { useLedger } from "@/hooks/useLedger";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatCard } from "@/components/dashboard/StatCard";
import { LedgerTable } from "@/components/dashboard/LedgerTable";
import { ProtocolDonut } from "@/components/dashboard/ProtocolDonut";
import { Skeleton } from "@/components/ui/skeleton";

const QUICK_ACTIONS = [
  { to: "/comprador", label: "Probar comprador", description: "Ejecuta un pago de prueba", icon: ShoppingCart },
  { to: "/vendedor", label: "Probar vendedor", description: "Ver el 402 sin pagar", icon: Store },
  { to: "/catalogo", label: "Ver catálogo", description: "Servicios disponibles", icon: Package },
  { to: "/comparar", label: "Comparar protocolos", description: "x402 vs. AP2", icon: GitCompare },
];

export function OverviewPage() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: ledger, isLoading: ledgerLoading } = useLedger(6);

  return (
    <AppShell title="Inicio" subtitle="Resumen del dashboard de agentic commerce">
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {statsLoading || !stats ? (
            Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)
          ) : (
            <>
              <StatCard icon={Activity} label="Llamadas de prueba" value={String(stats.total_calls)} />
              <StatCard
                icon={CheckCircle2}
                label="Exitosas"
                value={String(stats.successful_calls)}
                hint={stats.failed_calls > 0 ? `${stats.failed_calls} con error` : undefined}
                iconClassName="bg-success/10 text-success"
              />
              <StatCard
                icon={DollarSign}
                label="Total liquidado"
                value={`$${stats.total_paid_usd}`}
                iconClassName="bg-accent/10 text-accent"
              />
              <StatCard
                icon={Package}
                label="Modo / Red"
                value={stats.mode}
                hint={stats.network}
              />
            </>
          )}
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Acciones rápidas</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {QUICK_ACTIONS.map(({ to, label, description, icon: Icon }) => (
              <Link key={to} to={to}>
                <Card className="h-full transition-shadow hover:shadow-md">
                  <CardContent className="flex flex-col items-start gap-2 p-4">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Icon className="size-4" />
                    </div>
                    <p className="text-sm font-medium">{label}</p>
                    <p className="text-xs text-muted-foreground">{description}</p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>Actividad reciente</CardTitle>
              <Link to="/actividad" className="text-xs font-medium text-primary hover:underline">
                Ver todo
              </Link>
            </CardHeader>
            <CardContent>
              {ledgerLoading || !ledger ? (
                <Skeleton className="h-40" />
              ) : (
                <LedgerTable entries={ledger} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Llamadas por protocolo</CardTitle>
            </CardHeader>
            <CardContent>
              {statsLoading || !stats ? (
                <Skeleton className="h-40" />
              ) : (
                <ProtocolDonut callsByProtocol={stats.calls_by_protocol} />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
