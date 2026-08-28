import { ChevronDown, CircleDollarSign, Search, Wallet } from "lucide-react";
import type { TraceStep } from "@/types/agent";
import { truncateAddress } from "@/lib/format";
import { CopyButton } from "@/components/ui/copy-button";

const ACTION_LABEL: Record<TraceStep["action"], string> = {
  search_catalog: "Buscó en el catálogo",
  call_service: "Llamó y pagó un servicio",
  final_answer: "Respuesta final",
};

const ACTION_ICON: Record<TraceStep["action"], typeof Search> = {
  search_catalog: Search,
  call_service: Wallet,
  final_answer: CircleDollarSign,
};

interface CallServiceObservation {
  service_id?: string;
  price_paid_usd?: string | null;
  settlement_id?: string | null;
  data?: unknown;
  error?: string;
}

interface SearchCatalogObservation {
  results?: { id: string; name: string; price_usd: string; capability_tags: string[] }[];
  error?: string;
}

// Un paso de la traza ReAct del agente (RM-12): pensamiento -> acción ->
// observación. `<details>` nativo en vez de un componente Accordion propio
// -- no hay uno en components/ui/ y no vale la pena agregar uno para esto.
export function TraceStepView({ step }: { step: TraceStep }) {
  const Icon = ACTION_ICON[step.action];

  return (
    <details className="group rounded-lg border border-border" open={step.action !== "final_answer"}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm">
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-medium">
          Turno {step.turn}: {ACTION_LABEL[step.action]}
        </span>
      </summary>
      <div className="flex flex-col gap-2 border-t border-border px-3 py-2.5 text-xs">
        {step.thought && (
          <p className="italic text-muted-foreground">"{step.thought}"</p>
        )}
        <ObservationView action={step.action} observation={step.observation} />
      </div>
    </details>
  );
}

function ObservationView({ action, observation }: { action: TraceStep["action"]; observation: unknown }) {
  const obs = (observation ?? {}) as Record<string, unknown>;

  if (typeof obs.error === "string") {
    return <p className="text-destructive">{obs.error}</p>;
  }

  if (action === "search_catalog") {
    const results = (obs as SearchCatalogObservation).results ?? [];
    return (
      <ul className="flex flex-col gap-1">
        {results.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 rounded bg-secondary/60 px-2 py-1">
            <span className="truncate">{r.name}</span>
            <span className="shrink-0 font-mono text-muted-foreground">{r.price_usd}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (action === "call_service") {
    const call = obs as CallServiceObservation;
    return (
      <dl className="grid grid-cols-1 gap-1 rounded-lg bg-secondary/60 p-2">
        <Row label="Servicio" value={call.service_id ?? "?"} />
        {call.price_paid_usd && <Row label="Pagado" value={`$${call.price_paid_usd}`} />}
        {call.settlement_id && (
          <Row
            label="Liquidación"
            value={truncateAddress(call.settlement_id, 8)}
            copyValue={call.settlement_id}
            mono
          />
        )}
      </dl>
    );
  }

  return null;
}

function Row({
  label,
  value,
  copyValue,
  mono,
}: {
  label: string;
  value: string;
  copyValue?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <div className="flex min-w-0 items-center gap-1">
        <dd className={mono ? "truncate font-mono" : "truncate font-medium"}>{value}</dd>
        {copyValue && <CopyButton value={copyValue} />}
      </div>
    </div>
  );
}
