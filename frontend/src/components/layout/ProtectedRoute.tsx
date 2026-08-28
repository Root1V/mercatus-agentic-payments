import { Navigate, Outlet } from "react-router-dom";
import { useIsAuthenticated } from "@/hooks/useAuth";

export function ProtectedRoute() {
  const isAuthenticated = useIsAuthenticated();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
