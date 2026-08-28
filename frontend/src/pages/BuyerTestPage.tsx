import { useState } from "react";
import { CheckCircle2, Loader2, Wallet, XCircle } from "lucide-react";
import { useTestCall } from "@/hooks/useTestCall";
import type { ProtocolName } from "@/types/protocol";
import { truncateAddress } from "@/lib/format";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { ProtocolBadge } from "@/components/dashboard/ProtocolBadge";

const DEFAULT_TEXT =
  "El protocolo x402 revive el codigo de estado HTTP 402 para que agentes de IA paguen APIs " +
  "automaticamente. AP2 de Google agrega una capa de mandatos de autorizacion agnostica al riel " +
  "de pago. Ninguno de los dos ha ganado todavia la carrera de estandares.";

export function BuyerTestPage() {
  const [protocol, setProtocol] = useState<ProtocolName>("x402");
  const [text, setText] = useState(DEFAULT_TEXT);
  const [maxSentences, setMaxSentences] = useState(2);
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
          <CardHeader>
            <CardTitle>Configurar la llamada</CardTitle>
            <CardDescription>
              Servicio: <span className="font-medium text-foreground">text-summarizer</span> ($0.001/llamada)
            </CardDescription>
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
    </AppShell>
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
