import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/cn";

export function CopyButton({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API puede fallar (permisos, contexto no seguro) -- no rompe la UI.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label="Copiar al portapapeles"
      title="Copiar"
      className={cn(
        "shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
        className,
      )}
    >
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
    </button>
  );
}
