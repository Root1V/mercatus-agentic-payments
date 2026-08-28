import { LogOut, User } from "lucide-react";
import { useCurrentUser, useLogout } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";

interface TopbarProps {
  title: string;
  subtitle?: string;
}

export function Topbar({ title, subtitle }: TopbarProps) {
  const { data: user } = useCurrentUser();
  const logout = useLogout();

  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-6 py-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-2 rounded-full bg-secondary px-3 py-1.5 text-sm">
            <User className="size-4 text-muted-foreground" />
            {user.username}
          </div>
        )}
        <Button variant="ghost" size="sm" onClick={logout}>
          <LogOut className="size-4" />
          Salir
        </Button>
      </div>
    </header>
  );
}
