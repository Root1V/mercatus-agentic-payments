import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { Card } from "@/components/ui/card";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  hint?: string;
  iconClassName?: string;
}

export function StatCard({ icon: Icon, label, value, hint, iconClassName }: StatCardProps) {
  return (
    <Card className="flex items-center gap-4 p-4">
      <div
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary",
          iconClassName,
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-2xl font-semibold leading-tight">{value}</p>
        <p className="truncate text-sm text-muted-foreground">{label}</p>
        {hint && <p className="mt-0.5 truncate text-xs text-muted-foreground/80">{hint}</p>}
      </div>
    </Card>
  );
}
