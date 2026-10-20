import { useEffect, useState } from "react";

// Keep in sync with ROUTE_META in backend/app/spa.py.
export type Route = "" | "fundsxml-to-tpt" | "mapping";
export const ROUTES: Route[] = ["", "fundsxml-to-tpt", "mapping"];

function current(): Route {
  const path = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return (ROUTES as string[]).includes(path) ? (path as Route) : "";
}

export function navigate(route: Route): void {
  const target = "/" + route;
  if (window.location.pathname !== target) {
    window.history.pushState(null, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(current);
  useEffect(() => {
    const onPop = () => setRoute(current());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return route;
}
