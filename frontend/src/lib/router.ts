import { useEffect, useState } from "react";

// Keep in sync with ROUTE_META in backend/app/spa.py.
export type Route =
  | ""
  | "fundsxml-to-tpt"
  | "openfunds-to-fundsxml"
  | "fundsxml-to-openfunds"
  | "tpt-to-openfunds"
  | "openfunds-to-tpt"
  | "mapping"
  | "api-docs";
export const ROUTES: Route[] = [
  "",
  "fundsxml-to-tpt",
  "openfunds-to-fundsxml",
  "fundsxml-to-openfunds",
  "tpt-to-openfunds",
  "openfunds-to-tpt",
  "mapping",
  "api-docs",
];
// The server sends the right <title> for the first page; these keep it right after in-app navigation.
export const TITLES: Record<Route, string> = {
  "": "TPT to FundsXML Converter – Solvency II Tripartite Template V7/V8 (Free)",
  "fundsxml-to-tpt": "FundsXML to TPT Converter – FundsXML 4 to Tripartite Template Excel/CSV",
  "openfunds-to-fundsxml": "openfunds to FundsXML Converter – OFST fields, holdings and EMT/EPT/EET to FundsXML 4",
  "fundsxml-to-openfunds": "FundsXML to openfunds Converter – FundsXML 4 to openfunds Excel/CSV",
  "tpt-to-openfunds": "TPT to openfunds Converter – Tripartite Template to openfunds holdings (lossless)",
  "openfunds-to-tpt": "openfunds to TPT Converter – openfunds holdings to Tripartite Template V7/V8",
  mapping: "TPT ⇄ FundsXML field mapping – every TPT V7/V8 field and its FundsXML path",
  "api-docs": "TPT ⇄ FundsXML Converter API – convert from scripts with curl, PowerShell or Python",
};

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
  useEffect(() => {
    document.title = TITLES[route];
  }, [route]);
  return route;
}
