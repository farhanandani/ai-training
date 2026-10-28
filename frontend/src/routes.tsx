import type { RouteObject } from "react-router-dom";
// import { AccuracyPage, AtmDetailPage, DataPage, FleetPage, PlannerPage } from "./pages/placeholders";
import { AccuracyPage, DataPage, PlannerPage } from "./pages/placeholders";
import { AtmDetailPage } from "./pages/AtmDetail";
import { FleetPage } from "./pages/FleetOverview";

export const routes: RouteObject[] = [
  { path: "/", element: <FleetPage /> },
  { path: "/atm/:tid", element: <AtmDetailPage /> },
  { path: "/planner", element: <PlannerPage /> },
  { path: "/data", element: <DataPage /> },
  { path: "/accuracy", element: <AccuracyPage /> },
];
