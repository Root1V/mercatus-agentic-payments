import { AlertCircle, CheckCircle2 } from "lucide-react";
import type { LedgerEntry } from "@/types/ledger";
import { formatTimestamp, formatUsd, truncateAddress } from "@/lib/format";
import { ProtocolBadge } from "./ProtocolBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Todavía no hay actividad. Ejecuta una prueba de pago para verla acá.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Estado</TableHead>
          <TableHead>Protocolo</TableHead>
          <TableHead>Capacidad</TableHead>
          <TableHead>Pagador</TableHead>
          <TableHead>Receptor</TableHead>
          <TableHead>Monto</TableHead>
          <TableHead>Liquidación</TableHead>
          <TableHead>Cuándo</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell>
              {entry.status === "ok" ? (
                <CheckCircle2 className="size-4 text-success" />
              ) : (
                <AlertCircle className="size-4 text-destructive" />
              )}
            </TableCell>
            <TableCell>
              <ProtocolBadge protocol={entry.protocol} />
            </TableCell>
            <TableCell className="text-sm">{entry.capability}</TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">
              {truncateAddress(entry.payer)}
            </TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">
              {entry.pay_to ? truncateAddress(entry.pay_to) : "—"}
            </TableCell>
            <TableCell className="text-sm font-medium">{formatUsd(entry.amount_usd)}</TableCell>
            <TableCell className="max-w-40 truncate font-mono text-xs text-muted-foreground" title={entry.settlement_id}>
              {entry.settlement_id || (entry.detail ?? "—")}
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">
              {formatTimestamp(entry.timestamp)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
