import { type FormEvent, useState } from "react";
import { Bot, Loader2, Plus, Send, Settings as SettingsIcon, Trash2 } from "lucide-react";
import {
  useAgents,
  useAllLlmModels,
  useConversations,
  useCreateAgent,
  useCreateConversation,
  useDeleteAgent,
  useLlmModels,
  useLlmSettings,
  useMessages,
  useSendMessage,
  useUpdateLlmSettings,
} from "@/hooks/useAgents";
import type { CreateAgentInput, LlmSettings } from "@/types/agent";
import type { ProtocolName } from "@/types/protocol";
import { formatUsd } from "@/lib/format";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogCloseButton,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProtocolBadge } from "@/components/dashboard/ProtocolBadge";
import { TraceStepView } from "@/components/dashboard/TraceStepView";

const EMPTY_FORM: CreateAgentInput = {
  name: "",
  instructions: "",
  llm_model: "",
  protocol: "x402",
  spend_limit_usd: "",
};

export function AgentPlaygroundPage() {
  const { data: agents, isLoading: agentsLoading } = useAgents();
  const createAgent = useCreateAgent();
  const deleteAgent = useDeleteAgent();
  const llmModels = useLlmModels();

  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [form, setForm] = useState<CreateAgentInput>(EMPTY_FORM);
  const [deletingId, setDeletingId] = useState<number | undefined>();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: CreateAgentInput = {
      ...form,
      spend_limit_usd: form.spend_limit_usd ? form.spend_limit_usd : null,
    };
    createAgent.mutate(payload, {
      onSuccess: (agent) => {
        setOpen(false);
        setForm(EMPTY_FORM);
        setSelectedAgentId(agent.id);
      },
    });
  }

  function handleDelete(id: number) {
    setDeletingId(id);
    deleteAgent.mutate(id, {
      onSettled: () => setDeletingId(undefined),
      onSuccess: () => {
        if (selectedAgentId === id) setSelectedAgentId(null);
      },
    });
  }

  const selectedAgent = agents?.find((a) => a.id === selectedAgentId) ?? null;

  return (
    <AppShell
      title="Agentes"
      subtitle="Un agente de IA que decide si necesita una herramienta, la busca en el catálogo y paga por ella"
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <Card className="flex h-[calc(100vh-9rem)] flex-col">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>Mis agentes</CardTitle>
            <div className="flex items-center gap-1.5">
              <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
                <SettingsIcon className="size-4" />
              </Button>
              <Button size="sm" onClick={() => setOpen(true)}>
                <Plus className="size-4" /> Crear
              </Button>
            </div>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto">
            {agentsLoading || !agents ? (
              <Skeleton className="h-40" />
            ) : agents.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Todavía no creaste ningún agente.
              </p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {agents.map((agent) => (
                  <li key={agent.id}>
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setSelectedAgentId(agent.id)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg border px-3 py-2 pr-9 text-left text-sm transition-colors",
                          selectedAgentId === agent.id
                            ? "border-primary bg-primary/5"
                            : "border-border hover:bg-secondary/60",
                        )}
                      >
                        <div className="flex min-w-0 flex-col gap-1">
                          <span className="truncate font-medium">{agent.name}</span>
                          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <ProtocolBadge protocol={agent.protocol} />
                            <span className="truncate">{agent.llm_model}</span>
                          </span>
                        </div>
                      </button>
                      <button
                        type="button"
                        aria-label="Eliminar agente"
                        onClick={() => handleDelete(agent.id)}
                        disabled={deletingId === agent.id}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      >
                        {deletingId === agent.id ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="size-3.5" />
                        )}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {selectedAgent ? (
          <ChatPanel agentId={selectedAgent.id} spendLimitUsd={selectedAgent.spend_limit_usd} />
        ) : (
          <Card className="flex h-[calc(100vh-9rem)] items-center justify-center">
            <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
              <Bot className="size-8" />
              <p className="text-sm">Elegí o creá un agente para empezar a chatear.</p>
            </div>
          </Card>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogCloseButton onClick={() => setOpen(false)} />
        <DialogHeader>
          <DialogTitle>Nuevo agente</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1.5">
            <Label>Nombre</Label>
            <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Prompt / instrucciones (opcional)</Label>
            <Textarea
              rows={3}
              placeholder="Ej: sos un asistente de investigación conciso, respondé siempre en español."
              value={form.instructions}
              onChange={(e) => setForm({ ...form, instructions: e.target.value })}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Modelo</Label>
            {llmModels.isLoading && <Skeleton className="h-9" />}
            {llmModels.isError && (
              <>
                <p className="text-xs text-destructive">
                  No se pudieron listar los modelos de Prometheus -- escribilo a mano.
                </p>
                <Input
                  required
                  placeholder="ej: qwen2.5-7b-instruct"
                  value={form.llm_model}
                  onChange={(e) => setForm({ ...form, llm_model: e.target.value })}
                />
              </>
            )}
            {llmModels.isSuccess && (
              <Select
                required
                value={form.llm_model}
                onChange={(e) => setForm({ ...form, llm_model: e.target.value })}
              >
                <option value="" disabled>
                  Elegir modelo…
                </option>
                {llmModels.data.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </Select>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>Protocolo de pago</Label>
              <Tabs value={form.protocol} onValueChange={(v) => setForm({ ...form, protocol: v as ProtocolName })}>
                <TabsList>
                  <TabsTrigger value="x402">x402</TabsTrigger>
                  <TabsTrigger value="ap2">AP2</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Límite de gasto (USD)</Label>
              <Input
                placeholder="Sin límite"
                value={form.spend_limit_usd ?? ""}
                onChange={(e) => setForm({ ...form, spend_limit_usd: e.target.value })}
              />
            </div>
          </div>

          {createAgent.isError && (
            <p className="text-sm text-destructive">No se pudo crear el agente.</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={createAgent.isPending || !form.llm_model}>
              {createAgent.isPending ? "Creando…" : "Crear agente"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      <LlmSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </AppShell>
  );
}

function LlmSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: settings, isLoading, isError } = useLlmSettings();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogCloseButton onClick={() => onOpenChange(false)} />
      <DialogHeader>
        <DialogTitle>Configurar LLM (Prometheus)</DialogTitle>
        <DialogDescription>
          Conectá tu Prometheus local sin tocar el .env del servidor -- pedile estos datos a
          quien lo administra.
        </DialogDescription>
      </DialogHeader>
      {open && isLoading && <Skeleton className="h-48" />}
      {open && isError && (
        <p className="text-sm text-destructive">No se pudo cargar la configuración actual.</p>
      )}
      {open && !isLoading && !isError && (
        // `key` fuerza un remount (y por lo tanto un useState fresco) cada vez
        // que cambian los datos guardados -- así el form siempre arranca con
        // los valores reales, no con lo que quedó de una edición anterior.
        <LlmSettingsForm
          key={settings?.updated_at ?? "unconfigured"}
          settings={settings}
          onClose={() => onOpenChange(false)}
        />
      )}
    </Dialog>
  );
}

function LlmSettingsForm({
  settings,
  onClose,
}: {
  settings: LlmSettings | undefined;
  onClose: () => void;
}) {
  const updateSettings = useUpdateLlmSettings();
  const allModels = useAllLlmModels(!!settings?.configured);
  const [form, setForm] = useState({
    auth_base_url: settings?.auth_base_url ?? "",
    gateway_base_url: settings?.gateway_base_url ?? "",
    client_id: settings?.client_id ?? "",
    client_secret: "",
    allowed_models: settings?.allowed_models.join(", ") ?? "",
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    updateSettings.mutate({
      auth_base_url: form.auth_base_url,
      gateway_base_url: form.gateway_base_url,
      client_id: form.client_id,
      client_secret: form.client_secret ? form.client_secret : undefined,
      allowed_models: form.allowed_models
        .split(",")
        .map((m) => m.trim())
        .filter(Boolean),
    });
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label>URL del auth-service</Label>
          <Input
            required
            placeholder="http://localhost:9000"
            value={form.auth_base_url}
            onChange={(e) => setForm({ ...form, auth_base_url: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>URL del gateway</Label>
          <Input
            required
            placeholder="http://localhost:8020"
            value={form.gateway_base_url}
            onChange={(e) => setForm({ ...form, gateway_base_url: e.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Client ID</Label>
        <Input
          required
          value={form.client_id}
          onChange={(e) => setForm({ ...form, client_id: e.target.value })}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>{settings?.has_secret ? "Client secret (dejar vacío para no cambiarlo)" : "Client secret"}</Label>
        <Input
          type="password"
          required={!settings?.has_secret}
          placeholder={settings?.has_secret ? "••••••••" : ""}
          value={form.client_secret}
          onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Modelos habilitados (separados por coma -- vacío = todos)</Label>
        <Input
          placeholder="qwen2.5-7b-instruct, llama-3.1-8b"
          value={form.allowed_models}
          onChange={(e) => setForm({ ...form, allowed_models: e.target.value })}
        />
        {allModels.isSuccess && (
          <p className="text-xs text-muted-foreground">
            Disponibles en Prometheus: {allModels.data.map((m) => m.id).join(", ") || "ninguno"}
          </p>
        )}
      </div>

      {updateSettings.isError && (
        <p className="text-sm text-destructive">
          {(updateSettings.error as Error)?.message ?? "No se pudo guardar la configuración."}
        </p>
      )}
      {updateSettings.isSuccess && (
        <p className="text-sm text-success">Guardado -- ya podés elegir el modelo al crear un agente.</p>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cerrar
        </Button>
        <Button type="submit" disabled={updateSettings.isPending}>
          {updateSettings.isPending ? "Guardando…" : "Guardar conexión"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function ChatPanel({ agentId, spendLimitUsd }: { agentId: number; spendLimitUsd: string | null }) {
  const conversations = useConversations(agentId);
  const createConversation = useCreateConversation(agentId);
  const conversationId = conversations.data?.[0]?.id ?? null;

  const messages = useMessages(agentId, conversationId);
  const sendMessage = useSendMessage(agentId, conversationId);
  const [draft, setDraft] = useState("");

  function handleSend(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim() || conversationId === null) return;
    sendMessage.mutate(draft, { onSuccess: () => setDraft("") });
  }

  const noConversationYet = conversations.isSuccess && conversations.data.length === 0;

  return (
    <Card className="flex h-[calc(100vh-9rem)] flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border">
        <CardTitle>Chat</CardTitle>
        {spendLimitUsd && (
          <span className="text-xs text-muted-foreground">Límite de gasto: {formatUsd(spendLimitUsd)}</span>
        )}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3 overflow-y-auto pt-4">
        {conversations.isLoading && <Skeleton className="h-40" />}

        {noConversationYet && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <p className="text-sm text-muted-foreground">Todavía no hay ninguna conversación.</p>
            <Button
              size="sm"
              onClick={() => createConversation.mutate("Chat")}
              disabled={createConversation.isPending}
            >
              {createConversation.isPending ? "Creando…" : "Iniciar conversación"}
            </Button>
          </div>
        )}

        {conversationId !== null && messages.isLoading && <Skeleton className="h-40" />}

        {conversationId !== null &&
          messages.data?.map((message) => (
            <div
              key={message.id}
              className={cn("flex flex-col gap-2", message.role === "user" ? "items-end" : "items-start")}
            >
              <div
                className={cn(
                  "max-w-[85%] rounded-xl px-3 py-2 text-sm",
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary/60 text-foreground",
                )}
              >
                {message.content}
              </div>
              {message.role === "agent" && message.trace && message.trace.length > 0 && (
                <div className="flex w-full max-w-[85%] flex-col gap-1.5">
                  {message.trace.map((step) => (
                    <TraceStepView key={step.turn} step={step} />
                  ))}
                  {message.total_spent_usd && Number(message.total_spent_usd) > 0 && (
                    <p className="px-1 text-xs text-muted-foreground">
                      Total gastado en esta respuesta: {formatUsd(message.total_spent_usd)}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}

        {sendMessage.isPending && (
          <div className="flex items-center gap-2 self-start rounded-xl bg-secondary/60 px-3 py-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Pensando, buscando y pagando si hace falta…
          </div>
        )}

        {sendMessage.isError && (
          <p className="self-start text-xs text-destructive">
            {(sendMessage.error as Error)?.message ?? "El agente no pudo responder."}
          </p>
        )}
      </CardContent>

      <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-border p-3">
        <Textarea
          rows={1}
          placeholder="Escribile al agente…"
          value={draft}
          disabled={conversationId === null}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend(e);
            }
          }}
          className="min-h-9 flex-1 resize-none py-1.5"
        />
        <Button type="submit" size="icon" disabled={conversationId === null || sendMessage.isPending || !draft.trim()}>
          <Send className="size-4" />
        </Button>
      </form>
    </Card>
  );
}
