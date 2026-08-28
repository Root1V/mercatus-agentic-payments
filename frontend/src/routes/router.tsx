import { createBrowserRouter } from "react-router-dom";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { BuyerTestPage } from "@/pages/BuyerTestPage";
import { SellerTestPage } from "@/pages/SellerTestPage";
import { CatalogPage } from "@/pages/CatalogPage";
import { CompareProtocolsPage } from "@/pages/CompareProtocolsPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { AgentPlaygroundPage } from "@/pages/AgentPlaygroundPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      { path: "/", element: <OverviewPage /> },
      { path: "/comprador", element: <BuyerTestPage /> },
      { path: "/vendedor", element: <SellerTestPage /> },
      { path: "/catalogo", element: <CatalogPage /> },
      { path: "/comparar", element: <CompareProtocolsPage /> },
      { path: "/actividad", element: <ActivityPage /> },
      { path: "/agentes", element: <AgentPlaygroundPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
