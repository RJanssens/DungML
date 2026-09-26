// Typed wrappers around the FastAPI backend. The token is supplied by the
// OIDC AuthProvider via configureApi({ getToken }) on every request.
import type {
  CampaignState,
  ConnectivityResponse,
  Diagnostic,
  MapDetail,
  MapSummary,
  Project,
  ProjectMember,
  ProjectSession,
  RenderResponse,
  User,
  ValidateResponse,
} from "./types";

const TOKEN_KEY = "dungml.token";

// Runtime configuration. The SPA leaves these at their defaults (same-origin
// requests, token in localStorage). The embeddable widget calls configureApi()
// to point at a cross-origin dungml backend and supply a host-managed token.
let baseUrl = "";
let tokenSource: () => string | null = () =>
  localStorage.getItem(TOKEN_KEY);

export function configureApi(opts: {
  /** Origin of the dungml backend, e.g. "https://dungml.example.com".
   * Empty string (default) means same-origin. Trailing slash is trimmed. */
  baseUrl?: string;
  /** Returns the current bearer token (called on every request, so it can
   * return a freshly-refreshed token). Overrides the localStorage default. */
  getToken?: () => string | null;
}): void {
  if (opts.baseUrl !== undefined) baseUrl = opts.baseUrl.replace(/\/$/, "");
  if (opts.getToken !== undefined) tokenSource = opts.getToken;
}

/** Absolute URL for an API path, honouring the configured base origin. */
export function apiUrl(path: string): string {
  return `${baseUrl}${path}`;
}

/** Authorization header for the current token (empty if none). */
function authHeaders(): Record<string, string> {
  const tok = tokenSource();
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: { auth?: boolean; raw?: boolean } = { auth: true },
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false) Object.assign(headers, authHeaders());
  const res = await fetch(apiUrl(path), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: unknown = await res.text();
    try {
      detail = JSON.parse(detail as string);
    } catch {
      /* leave as text */
    }
    const msg =
      (typeof detail === "object" && detail && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : String(detail)) || `HTTP ${res.status}`;
    throw new ApiError(res.status, detail, msg);
  }
  if (res.status === 204) return undefined as T;
  if (opts.raw) return (await res.text()) as unknown as T;
  return (await res.json()) as T;
}

// ----- auth -----

// Password-based register/login/logout were removed in Plan 1 (OIDC replaces
// them). Only /api/auth/me remains — used by AuthProvider to fetch the display
// name after the OIDC token is obtained.
export const auth = {
  me: () => request<User>("GET", "/api/auth/me"),
};

// ----- projects -----

export const projects = {
  list: () => request<Project[]>("GET", "/api/projects"),
  create: (name: string, isPublic = true) =>
    request<Project>("POST", "/api/projects", { name, is_public: isPublic }),
  // Owner-only; the backend 403s anyone else.
  setPublic: (id: string, isPublic: boolean) =>
    request<Project>("PATCH", `/api/projects/${id}`, { is_public: isPublic }),
  get: (id: string) => request<Project>("GET", `/api/projects/${id}`),
  rename: (id: string, name: string) =>
    request<Project>("PATCH", `/api/projects/${id}`, { name }),
  remove: (id: string) =>
    request<void>("DELETE", `/api/projects/${id}`),
  importSamples: () =>
    request<Project>("POST", "/api/projects/import-samples"),
  // Who else can work on this project. The owner isn't in this list — it's
  // on the project itself, as `owner`.
  members: {
    list: (id: string) =>
      request<ProjectMember[]>("GET", `/api/projects/${id}/members`),
    // `identifier` is a subject or an email address of someone who has
    // signed in at least once; the backend 404s on anything else.
    add: (id: string, identifier: string) =>
      request<ProjectMember>("POST", `/api/projects/${id}/members`, {
        identifier,
      }),
    remove: (id: string, userId: string) =>
      request<void>("DELETE", `/api/projects/${id}/members/${userId}`),
  },
  // External campaigns (ttrpg2) driving a play session on this project.
  campaigns: (id: string) =>
    request<CampaignState[]>("GET", `/api/projects/${id}/campaigns`),
  // Every play session across the project's maps, newest activity first.
  sessions: (id: string) =>
    request<ProjectSession[]>("GET", `/api/projects/${id}/sessions`),
  // Download the whole project as a compressed `.dmapproj` archive. Uses a
  // direct fetch (not `request`) because the body is binary, and carries the
  // bearer token so the protected route authorises.
  export: async (id: string): Promise<Blob> => {
    const res = await fetch(apiUrl(`/api/projects/${id}/export`), {
      headers: authHeaders(),
    });
    if (!res.ok) throw new ApiError(res.status, null, `export failed (${res.status})`);
    return res.blob();
  },
  // Create a new project from an uploaded `.dmapproj` archive (multipart).
  import: async (file: File): Promise<Project> => {
    const fd = new FormData();
    fd.append("file", file);
    // Don't set Content-Type — the browser adds the multipart boundary.
    const res = await fetch(apiUrl("/api/projects/import"), {
      method: "POST",
      headers: authHeaders(),
      body: fd,
    });
    if (!res.ok) {
      let detail: unknown = await res.text();
      try {
        detail = JSON.parse(detail as string);
      } catch {
        /* leave as text */
      }
      const msg =
        typeof detail === "object" && detail && "detail" in detail
          ? String((detail as { detail: unknown }).detail)
          : `import failed (${res.status})`;
      throw new ApiError(res.status, detail, msg);
    }
    return res.json() as Promise<Project>;
  },
  // Bundled include libraries and whether this project already has each.
  libraryCatalog: (id: string) =>
    request<LibraryCatalogEntry[]>(
      "GET",
      `/api/projects/${id}/library-catalog`,
    ),
  // Copy a bundled library into the project as an editable library map.
  importLibrary: (id: string, name: string) =>
    request<MapDetail>("POST", `/api/projects/${id}/import-library`, { name }),
};

export interface LibraryCatalogEntry {
  name: string;
  added: boolean;
}

export interface FeatureGroup {
  source: string; // include filename, or "(this file)" for local defs
  names: string[];
}

// ----- maps -----

export const maps = {
  list: (projectId: string) =>
    request<MapSummary[]>("GET", `/api/projects/${projectId}/maps`),
  create: (projectId: string, name: string, source = "") =>
    request<MapDetail>("POST", `/api/projects/${projectId}/maps`, {
      name,
      source,
    }),
  get: (id: string) => request<MapDetail>("GET", `/api/maps/${id}`),
  update: (id: string, patch: { name?: string; source?: string }) =>
    request<MapDetail>("PUT", `/api/maps/${id}`, patch),
  remove: (id: string) => request<void>("DELETE", `/api/maps/${id}`),
  setDefault: (projectId: string, mapId: string) =>
    request<MapSummary>(
      "PUT",
      `/api/projects/${projectId}/maps/${mapId}/default`,
    ),
  // Project-aware preview: includes (e.g. `include "core.dmap"`) resolve
  // against the project's own maps. `source` is the live editor buffer.
  render: (id: string, source: string, renderer?: string) =>
    request<RenderResponse>("POST", `/api/maps/${id}/render`, {
      source,
      renderer,
    }),
  validate: (id: string, source: string) =>
    request<ValidateResponse>("POST", `/api/maps/${id}/validate`, { source }),
  // feature_def names available to the map (local + resolved includes),
  // sorted; drives the editor's feature dropdown.
  featureNames: (id: string, source: string) =>
    request<{ names: string[]; groups: FeatureGroup[] }>(
      "POST",
      `/api/maps/${id}/feature-names`,
      { source },
    ),
};

// ----- play sessions (fog-of-war) -----

export interface SessionExit {
  to: string; // node id, e.g. "room.hall"
  name: string; // bare name
  door: string; // door key
  type: string;
  state: string;
  blocked: boolean;
  discovered: boolean;
}

export interface SessionState {
  id: string;
  map_id: string;
  name: string;
  party_location: string | null;
  discovered_nodes: string[];
  discovered_doors: string[];
  exits: SessionExit[];
}

export const sessions = {
  list: (mapId: string) =>
    request<SessionState[]>("GET", `/api/maps/${mapId}/sessions`),
  create: (mapId: string, name: string, startLocation?: string) =>
    request<SessionState>("POST", `/api/maps/${mapId}/sessions`, {
      name,
      start_location: startLocation,
    }),
  get: (id: string) => request<SessionState>("GET", `/api/sessions/${id}`),
  remove: (id: string) => request<void>("DELETE", `/api/sessions/${id}`),
  move: (id: string, to: string) =>
    request<SessionState>("POST", `/api/sessions/${id}/move`, { to }),
  reveal: (id: string, node: string) =>
    request<SessionState>("POST", `/api/sessions/${id}/reveal`, { node }),
  render: (id: string, view: "discovered" | "full" = "discovered") =>
    request<{ svg: string }>(
      "GET",
      `/api/sessions/${id}/render?view=${view}`,
    ),
};

/** Fetch a pre-rendered fog SVG from an arbitrary (host-provided) URL, using
 * the configured bearer. Accepts raw image/svg+xml or a {svg} JSON envelope.
 * Used by the widget's "campaign mode", where the host (e.g. ttrpg3) owns the
 * session/fog state and just hands us a URL to poll. */
export async function fetchRenderSvg(renderUrl: string): Promise<string> {
  const res = await fetch(apiUrl(renderUrl), { headers: authHeaders() });
  if (!res.ok) throw new Error(`render ${res.status}`);
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const j = await res.json();
    return j.svg ?? "";
  }
  return res.text();
}

// ----- docs -----

export interface DocSummary {
  id: string;
  title: string;
}

export const docs = {
  list: () =>
    request<DocSummary[]>("GET", "/api/docs", undefined, { auth: false }),
  get: (id: string) =>
    request<string>("GET", `/api/docs/${id}`, undefined, {
      auth: false,
      raw: true,
    }),
};

// ----- dsl -----

export const dsl = {
  validate: (source: string) =>
    request<ValidateResponse>(
      "POST",
      "/api/dsl/validate",
      { source },
      { auth: false },
    ),
  render: (source: string, renderer?: string) =>
    request<RenderResponse>(
      "POST",
      "/api/dsl/render",
      { source, renderer },
      { auth: false },
    ),
  parse: (source: string) =>
    request<{ map: ParsedMap }>(
      "POST",
      "/api/dsl/parse",
      { source },
      { auth: false },
    ),
  renderers: () =>
    request<string[]>("GET", "/api/dsl/renderers", undefined, { auth: false }),
  connectivity: (source: string) =>
    request<ConnectivityResponse>(
      "POST",
      "/api/dsl/connectivity",
      { source },
      { auth: false },
    ),
};

// Minimal shape of the parsed DungeonMap model. We only type the
// fields the web app actually consumes (the print view); other
// fields are left as `unknown` to avoid drifting out of sync.
export interface ParsedFeatureInstance {
  ref: string;
  description?: string | null;
  dm_notes?: string | null;
}
export interface ParsedFeatureDef {
  name: string;
  display_name?: string | null;
  description?: string | null;
}
export interface ParsedRoom {
  name: string;
  label?: { text: string } | null;
  description?: string | null;
  dm_notes?: string | null;
  features: ParsedFeatureInstance[];
}
export interface ParsedLayer {
  name: string;
  hidden: boolean;
  rooms: ParsedRoom[];
}
export interface ParsedMapConfig {
  name: string;
  description?: string | null;
  dm_notes?: string | null;
}
export interface ParsedMap {
  map: ParsedMapConfig;
  feature_defs: Record<string, ParsedFeatureDef>;
  rooms: Record<string, ParsedRoom>;
  layers: ParsedLayer[];
}

export type { Diagnostic };
