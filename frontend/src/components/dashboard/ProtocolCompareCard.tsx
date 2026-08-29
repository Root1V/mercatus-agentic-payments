import type { ProtocolInfo } from "@/types/protocol";
import { truncateAddress } from "@/lib/format";
import { protocolTheme } from "@/lib/protocolTheme";
import { cn } from "@/lib/cn";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProtocolBadge } from "./ProtocolBadge";

export function ProtocolCompareCard({ protocol }: { protocol: ProtocolInfo }) {
  const theme = protocolTheme(protocol.name);
  return (
    <Card className="flex flex-col overflow-hidden">
      <div className={cn("h-1.5", theme.dotClass)} />
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{protocol.label}</CardTitle>
          <ProtocolBadge protocol={protocol.name} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <p className="text-sm text-muted-foreground">{protocol.description}</p>
        <dl className="grid grid-cols-1 gap-2 text-xs">
          <div className="flex items-center justify-between rounded-md bg-secondary/60 px-3 py-2">
            <dt className="text-muted-foreground">Red</dt>
            <dd className="font-mono">{protocol.network}</dd>
          </div>
          <div className="flex items-center justify-between rounded-md bg-secondary/60 px-3 py-2">
            <dt className="text-muted-foreground">Modo</dt>
            <dd className="capitalize">{protocol.mode}</dd>
          </div>
          <div className="flex items-center justify-between rounded-md bg-secondary/60 px-3 py-2">
            <dt className="text-muted-foreground">Vendedor (pay_to)</dt>
            <dd className="font-mono">{truncateAddress(protocol.seller_pay_to)}</dd>
          </div>
          <div className="flex items-center justify-between rounded-md bg-secondary/60 px-3 py-2">
            <dt className="text-muted-foreground">Comprador</dt>
            <dd className="font-mono">
              {protocol.buyer_address ? (
                truncateAddress(protocol.buyer_address)
              ) : (
                <span className="text-destructive">Wallet mal configurada</span>
              )}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
