import { Eye, Loader2, Lock } from "lucide-react";
import { useProtocols } from "@/hooks/useProtocols";
import { useSellerPreview } from "@/hooks/useSellerPreview";
import type { ProtocolName } from "@/types/protocol";
import { truncateAddress } from "@/lib/format";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ProtocolBadge } from "@/components/dashboard/ProtocolBadge";

export function SellerTestPage() {
  const { data: protocols, isLoading } = useProtocols();

  return (
    <AppShell
      title="Probar vendedor"
      subtitle="El servicio text-summarizer, monetizado en ambos protocolos — mirá el paywall antes de pagar"
    >
      {isLoading || !protocols ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {protocols.map((protocol) => (
            <SellerPreviewCard key={protocol.name} name={protocol.name} payTo={protocol.seller_pay_to} endpoint={protocol.endpoint} />
          ))}
        </div>
      )}
    </AppShell>
  );
}

function SellerPreviewCard({
  name,
  payTo,
  endpoint,
}: {
  name: ProtocolName;
  payTo: string;
  endpoint: string;
}) {
  const preview = useSellerPreview();

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            Vendedor <ProtocolBadge protocol={name} />
          </CardTitle>
          <CardDescription className="mt-1">$0.001 por llamada · pay_to {truncateAddress(payTo)}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="truncate rounded-md bg-secondary/60 px-3 py-2 font-mono text-xs text-muted-foreground">
          POST {endpoint}
        </p>

        <Button
          variant="outline"
          onClick={() => preview.mutate(name)}
          disabled={preview.isPending}
        >
          {preview.isPending ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Consultando…
            </>
          ) : (
            <>
              <Eye className="size-4" /> Ver 402 sin pagar
            </>
          )}
        </Button>

        {preview.data && (
          <div className="rounded-lg border border-border">
            <div className="flex items-center gap-2 border-b border-border bg-secondary/40 px-3 py-2 text-xs font-medium">
              <Lock className="size-3.5 text-muted-foreground" />
              HTTP {preview.data.status_code} — pago requerido
            </div>
            <pre className="max-h-64 overflow-auto p-3 text-[11px] leading-relaxed">
              {JSON.stringify(preview.data.body, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
