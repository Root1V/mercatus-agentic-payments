import { useProtocols } from "@/hooks/useProtocols";
import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/ui/skeleton";
import { ProtocolCompareCard } from "@/components/dashboard/ProtocolCompareCard";
import { Card, CardContent } from "@/components/ui/card";

export function CompareProtocolsPage() {
  const { data: protocols, isLoading } = useProtocols();

  return (
    <AppShell
      title="Comparar protocolos"
      subtitle="x402 (liquidación cripto directa) vs. AP2 (mandatos de autorización)"
    >
      <div className="flex flex-col gap-6">
        {isLoading || !protocols ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {protocols.map((protocol) => (
              <ProtocolCompareCard key={protocol.name} protocol={protocol} />
            ))}
          </div>
        )}

        <Card>
          <CardContent className="p-5 text-sm text-muted-foreground">
            <p>
              <strong className="text-foreground">x402</strong> liquida directo sobre USDC: el
              servidor responde 402, el comprador firma una autorización EIP-3009 y reintenta con
              el header <code className="rounded bg-secondary px-1 py-0.5">X-PAYMENT</code>.
            </p>
            <p className="mt-2">
              <strong className="text-foreground">AP2</strong> encadena mandatos firmados
              (Intent → Cart → Payment) agnósticos al riel de pago, y este framework liquida el
              mandato delegando en el mismo motor x402 — tal como la extensión oficial{" "}
              <code className="rounded bg-secondary px-1 py-0.5">a2a-x402</code> de Google.
            </p>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
