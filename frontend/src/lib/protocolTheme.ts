import type { ProtocolName } from "@/types/protocol";

interface ProtocolTheme {
  label: string;
  badgeClass: string;
  dotClass: string;
  chartColor: string;
}

/** Única fuente de verdad de color por protocolo -- usada por ProtocolBadge,
 * LedgerTable, CompareProtocolsPage y el donut del overview, para que x402
 * (azul) y AP2 (violeta) se vean siempre igual en toda la app. */
export const PROTOCOL_THEME: Record<ProtocolName, ProtocolTheme> = {
  x402: {
    label: "x402",
    badgeClass: "bg-protocol-x402/10 text-protocol-x402 border border-protocol-x402/20",
    dotClass: "bg-protocol-x402",
    chartColor: "hsl(217 91% 60%)",
  },
  ap2: {
    label: "AP2",
    badgeClass: "bg-protocol-ap2/10 text-protocol-ap2 border border-protocol-ap2/20",
    dotClass: "bg-protocol-ap2",
    chartColor: "hsl(262 83% 66%)",
  },
};

export function protocolTheme(name: string): ProtocolTheme {
  return PROTOCOL_THEME[name as ProtocolName] ?? {
    label: name,
    badgeClass: "bg-muted text-muted-foreground border border-border",
    dotClass: "bg-muted-foreground",
    chartColor: "hsl(215 16% 47%)",
  };
}
