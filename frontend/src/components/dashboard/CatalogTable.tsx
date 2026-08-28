import { Pencil, Trash2 } from "lucide-react";
import type { CatalogListing } from "@/types/catalog";
import { ProtocolBadge } from "./ProtocolBadge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface CatalogTableProps {
  listings: CatalogListing[];
  onEdit: (listing: CatalogListing) => void;
  onDelete: (id: string) => void;
  deletingId?: string;
}

export function CatalogTable({ listings, onEdit, onDelete, deletingId }: CatalogTableProps) {
  if (listings.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">El catálogo está vacío.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Servicio</TableHead>
          <TableHead>Precio</TableHead>
          <TableHead>Etiquetas</TableHead>
          <TableHead>Protocolos</TableHead>
          <TableHead>Proveedor</TableHead>
          <TableHead className="text-right">Acciones</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {listings.map((listing) => (
          <TableRow key={listing.id}>
            <TableCell>
              <p className="font-medium">{listing.name}</p>
              <p className="text-xs text-muted-foreground">{listing.description}</p>
            </TableCell>
            <TableCell className="text-sm font-medium">{listing.price_usd}</TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                {listing.capability_tags.map((tag) => (
                  <span key={tag} className="rounded-full bg-secondary px-2 py-0.5 text-xs">
                    {tag}
                  </span>
                ))}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex gap-1">
                {listing.protocols.map((protocol) => (
                  <ProtocolBadge key={protocol} protocol={protocol} />
                ))}
              </div>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{listing.provider_name}</TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onEdit(listing)}
                  aria-label={`Editar ${listing.name}`}
                >
                  <Pencil className="size-4 text-muted-foreground" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onDelete(listing.id)}
                  disabled={deletingId === listing.id}
                  aria-label={`Borrar ${listing.name}`}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
