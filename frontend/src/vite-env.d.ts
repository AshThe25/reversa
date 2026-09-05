/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin the API is served from. Empty when it shares an origin with the app. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
