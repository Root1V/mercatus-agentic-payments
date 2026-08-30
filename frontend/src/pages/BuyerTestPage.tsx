import { type FormEvent, useState } from "react";
import { CheckCircle2, Loader2, Settings as SettingsIcon, Wallet, XCircle } from "lucide-react";
import { useTestCall } from "@/hooks/useTestCall";
import { useUpdateWalletSettings, useWalletSettings } from "@/hooks/useWallet";
import type { ProtocolName } from "@/types/protocol";
import type { WalletBackend, WalletSettings as WalletSettingsData } from "@/types/wallet";
import { truncateAddress } from "@/lib/format";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogCloseButton,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CopyButton } from "@/components/ui/copy-button";
import { ProtocolBadge } from "@/components/dashboard/ProtocolBadge";

const WALLET_BACKEND_LABELS: Record<"local" | "circle" | "aibank", string> = {
  local: "wallet local",
  circle: "Circle",
  aibank: "AIBank",
};

const DEFAULT_TEXT =
  "El protocolo x402 revive el codigo de estado HTTP 402 para que agentes de IA paguen APIs " +
  "automaticamente. AP2 de Google agrega una capa de mandatos de autorizacion agnostica al riel " +
  "de pago. Ninguno de los dos ha ganado todavia la carrera de estandares.";

export function BuyerTestPage() {
  const [protocol, setProtocol] = useState<ProtocolName>("x402");
  const [text, setText] = useState(DEFAULT_TEXT);
  const [maxSentences, setMaxSentences] = useState(2);
  const [walletSettingsOpen, setWalletSettingsOpen] = useState(false);
  const testCall = useTestCall();

  function handleRun() {
    testCall.mutate({ protocol, capability: "summarize", text, max_sentences: maxSentences });
  }

  return (
    <AppShell
      title="Probar comprador"
      subtitle="Como agente comprador: descubre el servicio, paga automáticamente y recibe el resultado"
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle>Configurar la llamada</CardTitle>
              <CardDescription>
                Servicio: <span className="font-medium text-foreground">text-summarizer</span> ($0.001/llamada)
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => setWalletSettingsOpen(true)}>
              <SettingsIcon className="size-4" /> Configurar wallet
            </Button>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>Protocolo de pago</Label>
              <Tabs value={protocol} onValueChange={(v) => setProtocol(v as ProtocolName)}>
                <TabsList>
                  <TabsTrigger value="x402">x402</TabsTrigger>
                  <TabsTrigger value="ap2">AP2</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="text">Texto a resumir</Label>
              <Textarea
                id="text"
                rows={5}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="max-sentences">Oraciones en el resumen</Label>
              <Input
                id="max-sentences"
                type="number"
                min={1}
                max={5}
                className="w-24"
                value={maxSentences}
                onChange={(e) => setMaxSentences(Number(e.target.value) || 1)}
              />
            </div>

            <Button onClick={handleRun} disabled={testCall.isPending || !text.trim()} className="mt-1">
              {testCall.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Pagando y llamando…
                </>
              ) : (
                <>
                  <Wallet className="size-4" /> Ejecutar pago con {protocol === "x402" ? "x402" : "AP2"}
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Resultado</CardTitle>
            <CardDescription>Petición real: 402 sin pago, firma automática, reintento con prueba de pago.</CardDescription>
          </CardHeader>
          <CardContent>
            {testCall.isIdle && (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Configurá la llamada y presioná "Ejecutar pago".
              </p>
            )}

            {testCall.isPending && (
              <div className="flex flex-col items-center gap-2 py-10 text-sm text-muted-foreground">
                <Loader2 className="size-6 animate-spin text-primary" />
                Descubriendo servicio, firmando autorización y liquidando…
              </div>
            )}

            {testCall.isError && (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <XCircle className="size-8 text-destructive" />
                <p className="text-sm font-medium text-destructive">La llamada falló</p>
                <p className="text-xs text-muted-foreground">
                  {(testCall.error as Error)?.message ?? "Error desconocido"}
                </p>
              </div>
            )}

            {testCall.isSuccess && (
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-sm text-success">
                  <CheckCircle2 className="size-4" />
                  Pago liquidado en {testCall.data.elapsed_ms} ms
                </div>

                <div>
                  <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Resumen devuelto</p>
                  <p className="rounded-lg bg-secondary/60 p-3 text-sm">{testCall.data.result.summary}</p>
                </div>

                {testCall.data.receipt && (
                  <div>
                    <p className="mb-1 flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
                      Recibo de pago <ProtocolBadge protocol={testCall.data.receipt.protocol} />
                      {testCall.data.receipt.wallet_backend && (
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium normal-case text-secondary-foreground">
                          Firmado con {WALLET_BACKEND_LABELS[testCall.data.receipt.wallet_backend]}
                        </span>
                      )}
                    </p>
                    <dl className="grid grid-cols-1 gap-1.5 rounded-lg border border-border p-3 text-xs">
                      <Row label="Red" value={testCall.data.receipt.network} copyValue={testCall.data.receipt.network} mono />
                      <Row
                        label="Pagador"
                        value={truncateAddress(testCall.data.receipt.payer)}
                        copyValue={testCall.data.receipt.payer}
                        mono
                      />
                      <Row
                        label="Receptor"
                        value={truncateAddress(testCall.data.receipt.pay_to)}
                        copyValue={testCall.data.receipt.pay_to}
                        mono
                      />
                      <Row label="Monto" value={`$${testCall.data.receipt.amount_usd}`} />
                      <Row
                        label="ID de liquidación"
                        value={testCall.data.receipt.settlement_id}
                        copyValue={testCall.data.receipt.settlement_id}
                        mono
                      />
                    </dl>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <WalletSettingsDialog open={walletSettingsOpen} onOpenChange={setWalletSettingsOpen} />
    </AppShell>
  );
}

function WalletSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: settings, isLoading, isError } = useWalletSettings();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogCloseButton onClick={() => onOpenChange(false)} />
      <DialogHeader>
        <DialogTitle>Configurar wallet del comprador</DialogTitle>
        <DialogDescription>
          Con qué wallet firma el comprador (esta página y el playground de agentes). El
          vendedor de ejemplo no se administra desde acá.
        </DialogDescription>
      </DialogHeader>
      {open && isLoading && <Skeleton className="h-48" />}
      {open && isError && (
        <p className="text-sm text-destructive">No se pudo cargar la configuración actual.</p>
      )}
      {open && !isLoading && !isError && (
        <WalletSettingsForm
          key={settings?.updated_at ?? "unconfigured"}
          settings={settings}
          onClose={() => onOpenChange(false)}
        />
      )}
    </Dialog>
  );
}

function WalletSettingsForm({
  settings,
  onClose,
}: {
  settings: WalletSettingsData | undefined;
  onClose: () => void;
}) {
  const updateSettings = useUpdateWalletSettings();
  const [form, setForm] = useState({
    backend: settings?.backend ?? ("local" as WalletBackend),
    circle_api_key: "",
    circle_entity_secret: "",
    circle_wallet_id: settings?.circle_wallet_id ?? "",
    aibank_account_id: settings?.aibank_account_id ?? "",
    aibank_api_key: "",
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    updateSettings.mutate({
      backend: form.backend,
      circle_api_key: form.circle_api_key ? form.circle_api_key : undefined,
      circle_entity_secret: form.circle_entity_secret ? form.circle_entity_secret : undefined,
      circle_wallet_id: form.backend === "circle" ? form.circle_wallet_id : null,
      aibank_account_id: form.backend === "aibank" ? form.aibank_account_id || null : null,
      aibank_api_key: form.aibank_api_key ? form.aibank_api_key : undefined,
    });
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
      <div className="flex flex-col gap-1.5">
        <Label>Backend</Label>
        <Tabs value={form.backend} onValueChange={(v) => setForm({ ...form, backend: v as WalletBackend })}>
          <TabsList>
            <TabsTrigger value="local">Local (efímera)</TabsTrigger>
            <TabsTrigger value="circle">Circle</TabsTrigger>
            <TabsTrigger value="aibank">AIBank</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {form.backend === "circle" && (
        <>
          <div className="flex flex-col gap-1.5">
            <Label>
              {settings?.has_circle_api_key ? "API key de Circle (dejar vacío para no cambiarla)" : "API key de Circle"}
            </Label>
            <Input
              type="password"
              required={!settings?.has_circle_api_key}
              placeholder={settings?.has_circle_api_key ? "••••••••" : "TEST_API_KEY:..."}
              value={form.circle_api_key}
              onChange={(e) => setForm({ ...form, circle_api_key: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>
              {settings?.has_circle_entity_secret
                ? "Entity secret (dejar vacío para no cambiarlo)"
                : "Entity secret"}
            </Label>
            <Input
              type="password"
              required={!settings?.has_circle_entity_secret}
              placeholder={settings?.has_circle_entity_secret ? "••••••••" : "hex de 64 caracteres"}
              value={form.circle_entity_secret}
              onChange={(e) => setForm({ ...form, circle_entity_secret: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Wallet ID de Circle</Label>
            <Input
              required
              value={form.circle_wallet_id}
              onChange={(e) => setForm({ ...form, circle_wallet_id: e.target.value })}
            />
          </div>
        </>
      )}

      {form.backend === "aibank" && (
        <>
          <p className="rounded-lg bg-secondary/60 p-3 text-xs text-muted-foreground">
            Solo tiene efecto con el protocolo <span className="font-medium text-foreground">AP2</span>, y
            solo si el dashboard se inició con{" "}
            <code className="rounded bg-secondary px-1 py-0.5">AGENT_COMMERCE_AP2_SETTLEMENT=aibank</code> --
            el riel de liquidación de AP2 queda fijo al arrancar el proceso, no se puede cambiar en
            caliente.
          </p>
          <div className="flex flex-col gap-1.5">
            <Label>Cuenta de AIBank (opcional)</Label>
            <Input
              placeholder="se genera automático si lo dejás vacío"
              value={form.aibank_account_id}
              onChange={(e) => setForm({ ...form, aibank_account_id: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>
              {settings?.has_aibank_api_key
                ? "API key de AIBank (dejar vacío para no cambiarla)"
                : "API key de AIBank (opcional)"}
            </Label>
            <Input
              type="password"
              placeholder={settings?.has_aibank_api_key ? "••••••••" : "se genera automático si lo dejás vacío"}
              value={form.aibank_api_key}
              onChange={(e) => setForm({ ...form, aibank_api_key: e.target.value })}
            />
          </div>
        </>
      )}

      {updateSettings.isError && (
        <p className="text-sm text-destructive">
          {(updateSettings.error as Error)?.message ?? "No se pudo guardar la configuración."}
        </p>
      )}
      {updateSettings.isSuccess && (
        <p className="text-sm text-success">Guardado -- el próximo pago ya usa esta wallet.</p>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cerrar
        </Button>
        <Button type="submit" disabled={updateSettings.isPending}>
          {updateSettings.isPending ? "Guardando…" : "Guardar"}
        </Button>
      </DialogFooter>
    </form>
  );
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
