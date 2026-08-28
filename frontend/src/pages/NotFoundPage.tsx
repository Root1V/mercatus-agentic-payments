import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-secondary/40 text-center">
      <p className="text-5xl font-semibold text-muted-foreground">404</p>
      <p className="text-sm text-muted-foreground">Esta página no existe.</p>
      <Link to="/" className={buttonVariants()}>
        Volver al inicio
      </Link>
    </div>
  );
}
