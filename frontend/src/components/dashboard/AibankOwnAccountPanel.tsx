import { type ReactNode, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, Smartphone, XCircle } from "lucide-react";
import {
  useActivateConsentRequest,
  useAibankMandate,
  useConsentRequest,
  useCreateConsentRequest,
  useSimulateMandateRevocation,
  useSimulateTitularApproval,
  useSimulateTitularRejection,
} from "@/hooks/useAibank";
import type { AibankMandate, ConsentRequest } from "@/types/aibank";
import { apiErrorMessage, isNotFoundError } from "@/lib/apiError";
import { formatTimestamp, formatUsd } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

/**
 * AIBank modelo B (RM-18): conectar la cuenta propia de un cliente de AIBank,
 * con el flujo de `13-spec-modelos-a-y-b.md` §3 -- pedir permiso, el titular
 * decide en la app del banco, Mercatus lo descubre consultando y activa el
 * mandato. Va dentro de un `<form>` (el del diálogo de wallet), así que acá
 * no hay formularios anidados: solo botones `type="button"`.
 */
export function AibankOwnAccountPanel() {
  const mandateQuery = useAibankMandate(true);
  const [connecting, setConnecting] = useState(false);

  if (mandateQuery.isLoading) return <Skeleton className="h-40" />;
  if (mandateQuery.isError) {
    return <p className="text-sm text-destructive">{apiErrorMessage(mandateQuery.error)}</p>;
  }

  const state = mandateQuery.data;
  const liveMandate = state?.configured && state.found ? state : null;

  if (liveMandate && !connecting) {
    return <MandateSummary mandate={liveMandate} onRequestNew={() => setConnecting(true)} />;
  }

  return (
    <div className="flex flex-col gap-3">
      {state?.configured && !state.found && (
        <p className="rounded-lg bg-warning/10 p-3 text-xs text-foreground">
          El permiso guardado ya no existe en el banco simulado -- vive en memoria, así que un
          reinicio del dashboard lo pierde. Conectá la cuenta de nuevo.
        </p>
      )}
      <ConnectFlow onCancel={liveMandate ? () => setConnecting(false) : undefined} />
    </div>
  );
}

function MandateSummary({ mandate, onRequestNew }: { mandate: AibankMandate; onRequestNew: () => void }) {
  const revoke = useSimulateMandateRevocation();
  const total = Number(mandate.max_total_usd);
  const consumedPct = total > 0 ? Math.min(100, (Number(mandate.consumed_usd) / total) * 100) : 0;
  const isActive = mandate.status === "active";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Cuenta del titular</p>
            <div className="flex items-center gap-1">
              <p className="truncate font-mono text-sm">{mandate.account_id}</p>
              <CopyButton value={mandate.account_id} />
            </div>
          </div>
          <MandateStatusBadge status={mandate.status} />
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between text-xs tabular-nums">
            <span className="text-muted-foreground">Consumido del permiso</span>
            <span>
              <span className="font-medium text-foreground">{formatUsd(mandate.consumed_usd)}</span>
              <span className="text-muted-foreground"> de {formatUsd(mandate.max_total_usd)}</span>
            </span>
          </div>
          <div
            className="h-2 overflow-hidden rounded-full bg-secondary"
            role="meter"
            aria-label="Consumo del permiso"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={Number(mandate.consumed_usd)}
          >
            <div className="h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none" style={{ width: `${consumedPct}%` }} />
          </div>
          <p className="text-xs text-muted-foreground tabular-nums">
            Quedan <span className="text-foreground">{formatUsd(mandate.remaining_usd)}</span> · máximo{" "}
            {formatUsd(mandate.max_per_operation_usd)} por pago · vence {formatTimestamp(mandate.expires_at)}
          </p>
        </div>
      </div>

      {!isActive && (
        <p className="text-xs text-destructive">
          Los pagos nuevos van a fallar: el permiso está {mandate.status === "revoked" ? "revocado" : "vencido"}.
          Pedile un permiso nuevo al titular.
        </p>
      )}

      <Button type="button" variant="outline" size="sm" className="self-start" onClick={onRequestNew}>
        {isActive ? "Conectar otra cuenta" : "Pedir permiso nuevo"}
      </Button>

      {isActive && (
        <TitularSimulator>
          <p className="text-xs text-muted-foreground">
            El titular puede retirar el permiso cuando quiera. Las retenciones ya en curso no se cancelan.
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="self-start"
            disabled={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            {revoke.isPending ? "Revocando…" : "Revocar permiso como titular"}
          </Button>
          {revoke.isError && <p className="text-xs text-destructive">{apiErrorMessage(revoke.error)}</p>}
        </TitularSimulator>
      )}
    </div>
  );
}

function MandateStatusBadge({ status }: { status: AibankMandate["status"] }) {
  if (status === "active") return <Badge variant="success">Activo</Badge>;
  return <Badge variant="destructive">{status === "revoked" ? "Revocado" : "Vencido"}</Badge>;
}

function ConnectFlow({ onCancel }: { onCancel?: () => void }) {
  const [requestId, setRequestId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ max_per_operation_usd: "0.01", max_total_usd: "1.00", purpose: "" });
  const create = useCreateConsentRequest();
  const consent = useConsentRequest(requestId);
  const activate = useActivateConsentRequest();
  // StrictMode corre los efectos dos veces: sin esta guarda se activaría el
  // mismo permiso dos veces.
  const activatedFor = useRef<string | null>(null);

  const status = consent.data?.status;
  const { mutate: activateMutate } = activate;
  useEffect(() => {
    if (requestId && status === "approved" && activatedFor.current !== requestId) {
      activatedFor.current = requestId;
      activateMutate(requestId);
    }
  }, [requestId, status, activateMutate]);

  function reset() {
    setRequestId(null);
    activatedFor.current = null;
    create.reset();
    activate.reset();
  }

  function handleRequest() {
    create.mutate(draft, { onSuccess: (created) => setRequestId(created.consent_request_id) });
  }

  if (!requestId) {
    const canSubmit = draft.purpose.trim() && Number(draft.max_per_operation_usd) > 0 && Number(draft.max_total_usd) > 0;
    return (
      <div className="flex flex-col gap-3">
        <p className="rounded-lg bg-secondary/60 p-3 text-xs text-muted-foreground">
          Para un cliente que <span className="font-medium text-foreground">ya tiene cuenta en AIBank</span>: el
          agente paga desde la cuenta del cliente, con un permiso que el titular aprueba en la app del banco.
          El dinero nunca pasa por Mercatus. La solicitud no lleva cuenta: la elige el titular.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="consent-max-per-op">Máximo por pago (USD)</Label>
            <Input
              id="consent-max-per-op"
              type="number"
              min="0.000001"
              step="any"
              value={draft.max_per_operation_usd}
              onChange={(e) => setDraft({ ...draft, max_per_operation_usd: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="consent-max-total">Máximo total (USD)</Label>
            <Input
              id="consent-max-total"
              type="number"
              min="0.000001"
              step="any"
              value={draft.max_total_usd}
              onChange={(e) => setDraft({ ...draft, max_total_usd: e.target.value })}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="consent-purpose">Para qué se pide</Label>
          <Textarea
            id="consent-purpose"
            rows={2}
            placeholder="Pagos del agente de investigación de Acme S.A."
            value={draft.purpose}
            onChange={(e) => setDraft({ ...draft, purpose: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            El titular lo lee tal cual en la pantalla del banco. Un texto vago no le deja decidir bien.
          </p>
        </div>
        {create.isError && <p className="text-xs text-destructive">{apiErrorMessage(create.error)}</p>}
        <div className="flex gap-2">
          <Button type="button" size="sm" disabled={!canSubmit || create.isPending} onClick={handleRequest}>
            {create.isPending ? "Pidiendo…" : "Pedir permiso al titular"}
          </Button>
          {onCancel && (
            <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
              Cancelar
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (consent.isError) {
    return (
      <FlowFailure
        message={
          isNotFoundError(consent.error)
            ? "La solicitud venció sin respuesta (vive una hora)."
            : apiErrorMessage(consent.error)
        }
        onRetry={reset}
      />
    );
  }

  if (!consent.data) return <Skeleton className="h-32" />;

  if (consent.data.status === "rejected") {
    return <FlowFailure message="El titular rechazó el permiso." onRetry={reset} />;
  }

  if (consent.data.status === "approved") {
    if (activate.isError) {
      return <FlowFailure message={apiErrorMessage(activate.error)} onRetry={reset} />;
    }
    return (
      <div className="flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-sm text-success">
        {activate.isSuccess ? <CheckCircle2 className="size-4" /> : <Loader2 className="size-4 animate-spin" />}
        {activate.isSuccess
          ? "Cuenta conectada: el próximo pago AP2 sale de la cuenta del titular."
          : "El titular aprobó. Activando el permiso…"}
      </div>
    );
  }

  return <PendingConsent request={consent.data} onCancel={reset} />;
}

function PendingConsent({ request, onCancel }: { request: ConsentRequest; onCancel: () => void }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
        <div className="flex items-center gap-2 text-sm">
          <Smartphone className="size-4 text-primary" />
          <span className="font-medium">Compartile este código al cliente</span>
        </div>
        <div className="flex items-center gap-1 rounded-md bg-secondary/60 px-3 py-2">
          <code className="truncate font-mono text-sm">{request.handoff_code}</code>
          <CopyButton value={request.handoff_code} />
        </div>
        <p className="text-xs text-muted-foreground">
          Lo abre en la app de AIBank, se autentica con su dispositivo y elige desde qué cuenta concede hasta{" "}
          {formatUsd(request.max_total_usd)} ({formatUsd(request.max_per_operation_usd)} por pago). Puede conceder
          menos, nunca más. Vence {formatTimestamp(request.expires_at)}.
        </p>
        <p className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
          <Loader2 className="size-3.5 animate-spin" /> Esperando la decisión del titular…
        </p>
      </div>

      <ApprovalSimulator request={request} />

      <Button type="button" size="sm" variant="ghost" className="self-start" onClick={onCancel}>
        Descartar solicitud
      </Button>
    </div>
  );
}

function ApprovalSimulator({ request }: { request: ConsentRequest }) {
  const approve = useSimulateTitularApproval(request.consent_request_id);
  const reject = useSimulateTitularRejection(request.consent_request_id);
  const [accountId, setAccountId] = useState(() => `acc_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`);
  const [grantedTotal, setGrantedTotal] = useState("");
  const busy = approve.isPending || reject.isPending;

  return (
    <TitularSimulator>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sim-account">Cuenta elegida</Label>
          <Input
            id="sim-account"
            className="font-mono"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sim-total">Total concedido (USD)</Label>
          <Input
            id="sim-total"
            type="number"
            min="0.000001"
            step="any"
            placeholder={request.max_total_usd}
            value={grantedTotal}
            onChange={(e) => setGrantedTotal(e.target.value)}
          />
        </div>
      </div>
      {(approve.isError || reject.isError) && (
        <p className="text-xs text-destructive">{apiErrorMessage(approve.error ?? reject.error)}</p>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || !accountId.trim()}
          onClick={() =>
            approve.mutate({ account_id: accountId.trim(), max_total_usd: grantedTotal || undefined })
          }
        >
          {approve.isPending ? "Aprobando…" : "Aprobar como titular"}
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => reject.mutate()}>
          Rechazar
        </Button>
      </div>
    </TitularSimulator>
  );
}

/** Marca visualmente lo que en producción NO hace Mercatus: decidir como
 * titular. En AIBank real esto pasa en la app del banco, con el titular
 * autenticándose con su propio dispositivo. */
function TitularSimulator({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-warning/60 p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-warning">
        Simulador · reemplaza la app de AIBank
      </p>
      {children}
    </div>
  );
}

function FlowFailure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex items-center gap-2 text-sm text-destructive">
        <XCircle className="size-4" /> {message}
      </p>
      <Button type="button" size="sm" variant="outline" className="self-start" onClick={onRetry}>
        Pedir de nuevo
      </Button>
    </div>
  );
}
