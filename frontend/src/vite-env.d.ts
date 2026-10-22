/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Development only (lib/handoff): local instance of xml-viewer.online. */
  readonly VITE_XML_VIEWER_URL?: string;
  /** Development only (lib/handoff): local instance of findatex-validator.eu. */
  readonly VITE_FINDATEX_VALIDATOR_URL?: string;
}
