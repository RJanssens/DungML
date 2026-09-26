// Shared types mirroring the backend's Pydantic schemas.

export interface User {
  subject: string;
  email: string;
  username: string;
  name: string;
  display: string;
  roles: string[];
  is_service: boolean;
}

export interface TokenResponse {
  token: string;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  /** True when this project is reached through a membership, not ownership. */
  shared: boolean;
  /** Display label for the project's owner. */
  owner: string;
  /** Every signed-in user gets member rights on a public project. */
  is_public: boolean;
  /** How the caller reaches it. `shared` is `role !== "owner"`. */
  role: "owner" | "member" | "public";
}

export interface ProjectMember {
  user_id: string;
  subject: string;
  email: string;
}

/** An external campaign (ttrpg2) playing on one of this project's maps. */
export interface CampaignState {
  external_id: string;
  active_map_id: string | null;
  active_map_name: string | null;
  session_id: string | null;
  party_location: string | null;
  discovered_nodes: number;
  discovered_doors: number;
  /** Nodes in the active map — the denominator for `discovered_nodes`. */
  total_nodes: number;
  updated_at: string | null;
}

/** One play session anywhere in a project. */
export interface ProjectSession {
  session_id: string;
  name: string;
  map_id: string;
  map_name: string;
  party_location: string | null;
  discovered_nodes: number;
  total_nodes: number;
  /** Set when an external campaign (ttrpg2) drives this session. */
  external_id: string | null;
  updated_at: string | null;
}

export type MapKind = "map" | "library";

export interface MapSummary {
  id: string;
  project_id: string;
  name: string;
  kind: MapKind;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface MapDetail extends MapSummary {
  source: string;
}

export type Severity = "error" | "warning";

export interface Diagnostic {
  severity: Severity;
  message: string;
  line: number;
  column: number;
  end_line: number;
  end_column: number;
}

export interface ValidateResponse {
  diagnostics: Diagnostic[];
}

export interface RenderResponse {
  svg: string;
  diagnostics: Diagnostic[];
}

export interface NodeConnection {
  to: string; // neighbour node id, or "(exterior)"
  type: string;
  state: string;
  direction: "both" | "out" | "in";
}

export interface NodeConnectivity {
  id: string; // "room.hall" / "corridor.c1"
  kind: "room" | "corridor";
  name: string;
  connected: boolean;
  doors: number;
  connections: NodeConnection[];
}

export interface ConnectivityResponse {
  nodes: NodeConnectivity[];
}

export interface ApiError extends Error {
  status: number;
  detail: unknown;
}
