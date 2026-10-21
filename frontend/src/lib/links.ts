/**
 * Links to the sibling sites and the desktop app. They go through the same-origin
 * `/go/…` redirects (backend/app/api/go.py), so clicks show up in the usage statistics
 * and the sister site sees utm_source=tpt-converter.
 */
export const FAMILY: { key: string; label: string; href: string }[] = [
  { key: "xsd", label: "XSD Viewer", href: "/go/xsd-viewer" },
  { key: "xml", label: "XML Viewer", href: "/go/xml-viewer" },
  { key: "odata", label: "OData Viewer", href: "/go/odata-viewer" },
  { key: "desktop", label: "FreeXmlToolkit", href: "/go/freexmltoolkit" },
];

/** Server-rendered content pages (backend/app/content); plain links, not SPA routes. */
export const GUIDES_URL = "/guides";
export const FIELDS_URL = "/tpt/fields";
export const MESSAGES_URL = "/tpt/issues";
