// Shared types mirroring the backend's Pydantic schemas.

export interface User {
  id: string;
  email: string;
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
}

export type MapKind = "map" | "library";

export interface MapSummary {
  id: string;
  project_id: string;
  name: string;
  kind: MapKind;
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
