import { useState } from "react";
import { useLedger } from "@/hooks/useLedger";
import type { ProtocolName } from "@/types/protocol";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LedgerTable } from "@/components/dashboard/LedgerTable";
import { cn } from "@/lib/cn";

const FILTERS: { value: ProtocolName | "all"; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "x402", label: "x402" },
  { value: "ap2", label: "AP2" },
];

export function ActivityPage() {
  const { data: ledger, isLoading } = useLedger(200);
  const [filter, setFilter] = useState<ProtocolName | "all">("all");

  const filtered = ledger?.filter((entry) => filter === "all" || entry.protocol === filter) ?? [];

  return (
    <AppShell title="Actividad" subtitle="Historial completo de llamadas de prueba, persistido en Postgres">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Ledger</CardTitle>
          <div className="flex gap-1">
            {FILTERS.map(({ value, label }) => (
              <Button
                key={value}
                size="sm"
                variant={filter === value ? "default" : "outline"}
                className={cn("h-7 px-3 text-xs")}
                onClick={() => setFilter(value)}
              >
                {label}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {isLoading || !ledger ? <Skeleton className="h-64" /> : <LedgerTable entries={filtered} />}
        </CardContent>
      </Card>
    </AppShell>
  );
}
