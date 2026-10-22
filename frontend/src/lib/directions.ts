import type { Direction, Format } from "../types";
import type { Route } from "./router";

// Keep in sync with FORMATS / DEFAULT_TARGET in backend/app/service.py.
export const FORMATS: Format[] = ["tpt", "fundsxml", "openfunds"];
export const DEFAULT_TARGET: Record<Format, Format> = { tpt: "fundsxml", fundsxml: "tpt", openfunds: "fundsxml" };
export const FORMAT_LABEL: Record<Format, string> = { tpt: "TPT", fundsxml: "FundsXML", openfunds: "openfunds" };

export function parseDirection(direction: Direction): { source: Format; target: Format } {
  const [source, target] = direction.split("-to-") as [Format, Format];
  return { source, target };
}

export function makeDirection(source: Format, target: Format): Direction {
  const to = target === source ? DEFAULT_TARGET[source] : target;
  return `${source}-to-${to}` as Direction;
}

/** The converter page of a direction: TPT → FundsXML is the home page. */
export function routeOf(direction: Direction): Route {
  return direction === "tpt-to-fundsxml" ? "" : direction;
}

/** The direction of a converter page, or null for the other pages. */
export function directionOf(route: Route): Direction | null {
  if (route === "") return "tpt-to-fundsxml";
  return route.includes("-to-") ? (route as Direction) : null;
}

/**
 * The format a file is most likely in. The browser cannot tell a TPT from an openfunds spreadsheet;
 * for those the format of the current page is kept and the server decides (it sniffs the header).
 */
export function guessSource(file: File, current: Format): Format {
  const name = file.name.toLowerCase();
  if (name.endsWith(".xml")) return "fundsxml";
  if (name.endsWith(".zip")) return "openfunds";
  return current === "fundsxml" ? "tpt" : current;
}

export const ACCEPT: Record<Format, string> = {
  tpt: ".xlsx,.xlsm,.csv,.txt,.tsv",
  fundsxml: ".xml",
  openfunds: ".xlsx,.xlsm,.csv,.txt,.tsv,.zip",
};
