import { type FormEvent, type ReactNode, useState } from "react";
import { Plus } from "lucide-react";
import {
  useCatalog,
  useCreateCatalogListing,
  useDeleteCatalogListing,
  useUpdateCatalogListing,
} from "@/hooks/useCatalog";
import type { CatalogListing } from "@/types/catalog";
import type { ProtocolName } from "@/types/protocol";
import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogCloseButton, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CatalogTable } from "@/components/dashboard/CatalogTable";

const EMPTY_FORM = {
  id: "",
  name: "",
  description: "",
  method: "POST" as "GET" | "POST",
  url: "",
  price_usd: "$0.001",
  capability_tags: "",
  protocols: ["x402"] as ProtocolName[],
  provider_name: "agent_commerce demo",
};

function listingToForm(listing: CatalogListing): typeof EMPTY_FORM {
  return {
    id: listing.id,
    name: listing.name,
    description: listing.description,
    method: listing.method,
    url: listing.url,
    price_usd: listing.price_usd,
    capability_tags: listing.capability_tags.join(", "),
    protocols: listing.protocols,
    provider_name: listing.provider_name,
  };
}

export function CatalogPage() {
  const { data: listings, isLoading } = useCatalog();
  const createListing = useCreateCatalogListing();
  const updateListing = useUpdateCatalogListing();
  const deleteListing = useDeleteCatalogListing();
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [deletingId, setDeletingId] = useState<string | undefined>();

  const isEditing = editingId !== null;
  const mutation = isEditing ? updateListing : createListing;

  function openCreateDialog() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setOpen(true);
  }

  function openEditDialog(listing: CatalogListing) {
    setEditingId(listing.id);
    setForm(listingToForm(listing));
    setOpen(true);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload = {
      ...form,
      capability_tags: form.capability_tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    };
    const onSuccess = () => {
      setOpen(false);
      setForm(EMPTY_FORM);
      setEditingId(null);
    };
    if (isEditing) {
      updateListing.mutate({ id: editingId, input: payload }, { onSuccess });
    } else {
      createListing.mutate(payload, { onSuccess });
    }
  }

  function handleDelete(id: string) {
    setDeletingId(id);
    deleteListing.mutate(id, { onSettled: () => setDeletingId(undefined) });
  }

  return (
    <AppShell title="Catálogo" subtitle="Servicios de exhibición del marketplace simulado">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Servicios</CardTitle>
          <Button size="sm" onClick={openCreateDialog}>
            <Plus className="size-4" /> Agregar servicio
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading || !listings ? (
            <Skeleton className="h-40" />
          ) : (
            <CatalogTable
              listings={listings}
              onEdit={openEditDialog}
              onDelete={handleDelete}
              deletingId={deletingId}
            />
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogCloseButton onClick={() => setOpen(false)} />
        <DialogHeader>
          <DialogTitle>{isEditing ? "Editar servicio" : "Nuevo servicio del catálogo"}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="ID (slug)">
              <Input
                required
                disabled={isEditing}
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
              />
            </Field>
            <Field label="Precio">
              <Input
                required
                value={form.price_usd}
                onChange={(e) => setForm({ ...form, price_usd: e.target.value })}
              />
            </Field>
          </div>
          <Field label="Nombre">
            <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Descripción">
            <Textarea
              required
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Método">
              <Select
                value={form.method}
                onChange={(e) => setForm({ ...form, method: e.target.value as "GET" | "POST" })}
              >
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </Select>
            </Field>
            <Field label="Protocolos">
              <Select
                value={form.protocols[0]}
                onChange={(e) => setForm({ ...form, protocols: [e.target.value as ProtocolName] })}
              >
                <option value="x402">x402</option>
                <option value="ap2">AP2</option>
              </Select>
            </Field>
          </div>
          <Field label="URL">
            <Input
              required
              placeholder="http://127.0.0.1:8901/mi-servicio"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
            />
          </Field>
          <Field label="Proveedor">
            <Input
              required
              placeholder="agent_commerce demo"
              value={form.provider_name}
              onChange={(e) => setForm({ ...form, provider_name: e.target.value })}
            />
          </Field>
          <Field label="Etiquetas (separadas por coma)">
            <Input
              placeholder="summarize, nlp"
              value={form.capability_tags}
              onChange={(e) => setForm({ ...form, capability_tags: e.target.value })}
            />
          </Field>

          {mutation.isError && (
            <p className="text-sm text-destructive">
              {isEditing
                ? "No se pudo actualizar el listing."
                : "No se pudo crear el listing (¿el ID ya existe?)."}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Guardando…" : isEditing ? "Guardar cambios" : "Crear"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
