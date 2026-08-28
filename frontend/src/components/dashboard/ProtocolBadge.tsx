import { cn } from "@/lib/cn";
import { protocolTheme } from "@/lib/protocolTheme";

export function ProtocolBadge({ protocol, className }: { protocol: string; className?: string }) {
  const theme = protocolTheme(protocol);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        theme.badgeClass,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", theme.dotClass)} />
      {theme.label}
    </span>
  );
}
