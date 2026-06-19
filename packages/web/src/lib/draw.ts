// Drawing-tool helpers: map preview clicks to world coordinates and emit
// .dmap snippets. The rendered SVG's viewBox is already in world units and
// carries `data-map-h` / `data-origin`, so screen→world is a plain rescale
// off the <svg> bounding box (robust across browsers — no getScreenCTM).

export type Tool =
  | "select"
  | "rect"
  | "circle"
  | "polygon"
  | "cave"
  | "corridor"
  | "door"
  | "feature"
  | "text"
  | "area"
  | "line";

/** Click-to-add-vertex tools (the rest are drag or single-click). */
export const VERTEX_TOOLS: ReadonlySet<Tool> = new Set<Tool>([
  "polygon",
  "cave",
  "area",
  "line",
]);

/** Single-click tools that drop a built-in feature glyph in one cell. */
export const FEATURE_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["feature"]);

/** Single-click tools that drop freestanding text at the click point. */
export const TEXT_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["text"]);

/** Tools whose shape is drawn by a press-drag-release gesture. The rest are
 *  click-to-add-vertex (finish with double-click / Enter, cancel with Esc). */
export const DRAG_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["rect", "circle"]);

export interface MapMeta {
  mapH: number; // world-unit height of the map area (excludes any legend)
  origin: "top-left" | "bottom-left";
}

export interface Pt {
  x: number;
  y: number;
}

export function readMapMeta(svg: SVGSVGElement): MapMeta {
  const mapH =
    parseFloat(svg.getAttribute("data-map-h") ?? "") ||
    svg.viewBox.baseVal.height;
  const origin =
    svg.getAttribute("data-origin") === "bottom-left"
      ? "bottom-left"
      : "top-left";
  return { mapH, origin };
}

/** Client pixel → SVG user space (== world x, and world y before any flip). */
export function screenToSvg(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number,
): Pt {
  const rect = svg.getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  // width/height attrs share the viewBox aspect ratio, so there is no
  // letterboxing and the mapping is a straight linear rescale.
  return {
    x: (vb.width * (clientX - rect.left)) / rect.width,
    y: (vb.height * (clientY - rect.top)) / rect.height,
  };
}

export function svgToWorld(p: Pt, meta: MapMeta): Pt {
  return { x: p.x, y: meta.origin === "bottom-left" ? meta.mapH - p.y : p.y };
}

export function worldToSvg(p: Pt, meta: MapMeta): Pt {
  // Flip is its own inverse.
  return { x: p.x, y: meta.origin === "bottom-left" ? meta.mapH - p.y : p.y };
}

export function snapPt(p: Pt, snap: boolean, step = 1): Pt {
  if (snap)
    return { x: Math.round(p.x / step) * step, y: Math.round(p.y / step) * step };
  return { x: round2(p.x), y: round2(p.y) };
}

/** Snap to the centre of a grid cell (single-cell features sit mid-cell). */
export function snapCellCenter(p: Pt, snap: boolean, resolution = 1): Pt {
  if (snap) {
    // Snap to the centre of each (1/resolution)-sized sub-cell, so res 1 is
    // the whole-cell centre (x.5) and res 2 gives twice as many dots, etc.
    const n = Math.max(1, resolution);
    return {
      x: Math.floor(p.x * n) / n + 0.5 / n,
      y: Math.floor(p.y * n) / n + 0.5 / n,
    };
  }
  return { x: round2(p.x), y: round2(p.y) };
}

export function dist(a: Pt, b: Pt): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function num(v: number): string {
  return Number.isInteger(v) ? String(v) : String(round2(v));
}

/** Locate a `room "name"` / `corridor "name"` declaration in the source.
 *  Returns a 1-based {line, column} at the keyword, or null if not found. */
export function findDefinition(
  source: string,
  kind: string,
  name: string,
): { line: number; column: number } | null {
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`^([ \\t]*)(${kind})\\s+"${esc}"`, "m");
  const m = re.exec(source);
  if (!m) return null;
  const kwIdx = m.index + m[1].length;
  const before = source.slice(0, kwIdx);
  return { line: before.split("\n").length, column: kwIdx - before.lastIndexOf("\n") };
}

// ---- source sorting (the "Sort" button) ----

// Top-level keyword -> ordering rank. Structural items (include/map/feature_def)
// must stay before content; rooms, corridors, doors, then features as requested;
// the rest trail after, each keeping its original order.
const SORT_RANK: Record<string, number> = {
  include: 0,
  map: 1,
  scenario: 1,
  feature_def: 2,
  room: 3,
  corridor: 4,
  door: 5,
  window: 6,
  feature: 7,
  slice: 8,
  area: 9,
  marker: 10,
  text: 11,
  layer: 12,
};
const SORT_KEYWORDS = Object.keys(SORT_RANK);

interface TopBlock {
  kw: string;
  id: string; // quoted id for room/corridor (drives the sort), else ""
  start: number; // index of the keyword
}

/** Find every top-level declaration, brace/string/comment aware. */
function scanTopLevel(src: string): TopBlock[] {
  const out: TopBlock[] = [];
  let i = 0;
  let depth = 0;
  let comment = false;
  let str: '"' | '"""' | null = null;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    if (comment) {
      if (c === "\n") comment = false;
      i++;
      continue;
    }
    if (str === '"""') {
      if (src.startsWith('"""', i)) { str = null; i += 3; } else i++;
      continue;
    }
    if (str === '"') {
      if (c === "\\") i += 2;
      else { if (c === '"') str = null; i++; }
      continue;
    }
    if (c === "#") { comment = true; i++; continue; }
    if (src.startsWith('"""', i)) { str = '"""'; i += 3; continue; }
    if (c === '"') { str = '"'; i++; continue; }
    if (c === "{") { depth++; i++; continue; }
    if (c === "}") { depth = Math.max(0, depth - 1); i++; continue; }
    if (depth === 0 && /[A-Za-z_]/.test(c) && !/[A-Za-z0-9_]/.test(src[i - 1] ?? "\n")) {
      let j = i;
      while (j < n && /[A-Za-z0-9_]/.test(src[j])) j++;
      const word = src.slice(i, j);
      if (SORT_KEYWORDS.includes(word)) {
        let id = "";
        if (word === "room" || word === "corridor") {
          const m = /\s+"([^"]*)"/.exec(src.slice(j, j + 200));
          if (m) id = m[1];
        }
        out.push({ kw: word, id, start: i });
      }
      i = j;
      continue;
    }
    i++;
  }
  return out;
}

/** Reorder top-level declarations: rooms (by id), corridors (by id), doors,
 *  features — with structural items kept on top. Exact block text (including
 *  comments) is preserved; returns the source unchanged if it can't split it
 *  losslessly. */
export function sortSource(src: string): string {
  const blocks = scanTopLevel(src);
  if (blocks.length < 2) return src;

  const lineStart = (pos: number) => src.lastIndexOf("\n", pos - 1) + 1;
  // Extend a block's start up over immediately-preceding blank/comment lines
  // so per-declaration comments travel with their declaration.
  const blockStart = (kwPos: number) => {
    let ls = lineStart(kwPos);
    while (ls > 0) {
      const prevLs = lineStart(ls - 1);
      const prevLine = src.slice(prevLs, ls - 1).trim();
      if (prevLine === "" || prevLine.startsWith("#")) ls = prevLs;
      else break;
    }
    return ls;
  };

  const starts = [lineStart(blocks[0].start)]; // header stays in the preamble
  for (let k = 1; k < blocks.length; k++) starts.push(blockStart(blocks[k].start));
  const preamble = src.slice(0, starts[0]);

  const items = blocks.map((b, k) => ({
    ...b,
    text: src.slice(starts[k], k + 1 < starts.length ? starts[k + 1] : src.length),
    idx: k,
  }));

  // Lossless guard: original order must reconstruct the source exactly.
  if (preamble + items.map((it) => it.text).join("") !== src) return src;

  items.sort((a, b) => {
    const ra = SORT_RANK[a.kw];
    const rb = SORT_RANK[b.kw];
    if (ra !== rb) return ra - rb;
    if (a.kw === "room" || a.kw === "corridor") {
      const c = a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: "base" });
      if (c) return c;
    }
    return a.idx - b.idx; // stable within a group
  });

  const parts = [preamble.trim(), ...items.map((it) => it.text.trim())].filter(Boolean);
  return parts.join("\n\n") + "\n";
}

// ---- cell_grid map-block toggle (the editor "Cell grid" checkbox) ----

const CELL_GRID_RE = /^[ \t]*cell_grid\b.*$/m;

export function hasCellGrid(source: string): boolean {
  return CELL_GRID_RE.test(source);
}

/** Add or remove a `cell_grid` line in the map block. */
export function setCellGrid(source: string, on: boolean): string {
  const has = CELL_GRID_RE.test(source);
  if (on && !has) {
    const m = /\bmap\s+"[^"]*"\s*\{[^\n]*\n/.exec(source);
    if (!m) return source;
    const at = m.index + m[0].length;
    return source.slice(0, at) + "  cell_grid\n" + source.slice(at);
  }
  if (!on && has) {
    return source.replace(/^[ \t]*cell_grid\b.*\n?/m, "");
  }
  return source;
}

/** A fresh `name_N` not already quoted anywhere in the source. */
export function uniqueName(source: string, base: string): string {
  let i = 1;
  while (new RegExp(`"${base}_${i}"`).test(source)) i++;
  return `${base}_${i}`;
}

// ---- snippet emitters (each returns a block to append to the source) ----

export function emitRect(name: string, a: Pt, b: Pt): string {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);
  return `\nroom "${name}" {\n  rect ${num(x)},${num(y)} ${num(w)} x ${num(h)}\n  label "${name}"\n}\n`;
}

export function emitCircle(name: string, center: Pt, edge: Pt): string {
  const r = round2(dist(center, edge));
  return `\nroom "${name}" {\n  circle at ${num(center.x)},${num(center.y)} radius ${num(r)}\n  label "${name}"\n}\n`;
}

export function emitPolygon(name: string, pts: Pt[], organic = false): string {
  const body = pts.map((p) => `(${num(p.x)},${num(p.y)})`).join(" ");
  const ls = organic ? "\n  line_style organic" : "";
  return `\nroom "${name}" {\n  polygon ${body}${ls}\n  label "${name}"\n}\n`;
}

// Corridors are emitted in the `node`/`run` form so a single corridor can
// branch: shared nodes become T-junctions / crossings, and the whole thing
// stays one connected node in the map graph.
export function emitCorridor(
  name: string,
  nodes: Pt[],
  runs: [number, number][],
  width = 1,
  organic = false,
  straight = false,
): string {
  const nodeLines = nodes.map(
    (p, i) => `  node n${i + 1} at ${num(p.x)},${num(p.y)}`,
  );
  const runLines = runs.map(([a, b]) => `  run n${a + 1} to n${b + 1}`);
  const ls = organic ? "\n  line_style organic" : "";
  const cn = straight ? "\n  corners straight" : "";
  return `\ncorridor "${name}" {\n  width ${width}${ls}${cn}\n${nodeLines.join("\n")}\n${runLines.join("\n")}\n}\n`;
}

/** A completed drawing, handed from the preview to the editor. The editor
 *  owns the source text, so it picks the unique name and builds the block. */
export type DraftShape =
  | { kind: "rect"; a: Pt; b: Pt }
  | { kind: "circle"; center: Pt; edge: Pt }
  | { kind: "polygon"; pts: Pt[] }
  | { kind: "cave"; pts: Pt[] }
  | {
      kind: "corridor";
      nodes: Pt[];
      runs: [number, number][];
      organic?: boolean;
      straight?: boolean;
    }
  | {
      kind: "door";
      at: Pt;
      connects: string[]; // e.g. ["room.hall", "corridor.c1"]
      doorType: string;
      state: string;
      facing: string; // "auto" → let the renderer infer the leaf side
      trapped?: boolean;
    }
  | { kind: "feature"; at: Pt; ref: string; rotate?: number; scale?: number }
  | { kind: "text"; at: Pt; content: string; size?: number }
  | { kind: "area"; pts: Pt[]; areaKind: string; organic?: boolean }
  | { kind: "lineFeature"; pts: Pt[]; lineKind: string };

export function emitShape(source: string, shape: DraftShape): string {
  switch (shape.kind) {
    case "rect":
      return emitRect(uniqueName(source, "room"), shape.a, shape.b);
    case "circle":
      return emitCircle(uniqueName(source, "room"), shape.center, shape.edge);
    case "polygon":
      return emitPolygon(uniqueName(source, "room"), shape.pts);
    case "cave":
      return emitPolygon(uniqueName(source, "cave"), shape.pts, true);
    case "corridor":
      return emitCorridor(
        uniqueName(source, "corridor"),
        shape.nodes,
        shape.runs,
        1,
        shape.organic ?? false,
        shape.straight ?? false,
      );
    case "door":
      return emitDoor(
        shape.at,
        shape.connects,
        shape.doorType,
        shape.state,
        shape.facing,
        shape.trapped ?? false,
      );
    case "feature":
      return emitFeature(shape.at, shape.ref, shape.rotate ?? 0, shape.scale ?? 1);
    case "text":
      return emitText(shape.at, shape.content, shape.size ?? 1);
    case "area":
      return emitArea(
        uniqueName(source, "area"),
        shape.pts,
        shape.areaKind,
        shape.organic ?? false,
      );
    case "lineFeature":
      return emitLineFeature(
        uniqueName(source, "line"),
        shape.pts,
        shape.lineKind,
      );
  }
}

/** A styled polyline decoration (bars / curtain / barred). */
export function emitLineFeature(
  name: string,
  pts: Pt[],
  kind: string,
): string {
  const body = pts.map((p) => `point ${num(p.x)},${num(p.y)}`).join(" ");
  return `\nline_feature "${name}" kind ${kind} {\n  ${body}\n}\n`;
}

/** A decorative terrain area (water / lava / pit / …) as an irregular
 *  polygon. Not a room — excluded from the connectivity graph. */
export function emitArea(
  name: string,
  pts: Pt[],
  kind: string,
  organic = false,
): string {
  const body = pts.map((p) => `(${num(p.x)},${num(p.y)})`).join(" ");
  const ls = organic ? "\n  line_style organic" : "";
  return `\narea "${name}" kind ${kind} {\n  polygon ${body}${ls}\n}\n`;
}

/** Freestanding text at a fixed map position. `\"` is escaped so quotes in
 *  the content don't terminate the DSL string. */
export function emitText(at: Pt, content: string, size = 1): string {
  const safe = content.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  let s = `\ntext "${safe}" at ${num(at.x)},${num(at.y)}`;
  if (size !== 1) s += ` size ${num(size)}`;
  return s + "\n";
}

export function emitFeature(
  at: Pt,
  ref: string,
  rotate = 0,
  scale = 1,
): string {
  // Bare identifiers stay unquoted; ids with hyphens (e.g. stairs-up) need quotes.
  const r = /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(ref) ? ref : `"${ref}"`;
  let s = `\nfeature ${r} at ${num(at.x)},${num(at.y)}`;
  if (rotate) s += ` rotate ${num(rotate)}`;
  if (scale !== 1) s += ` scale ${num(scale)}`;
  return s + "\n";
}

export function emitDoor(
  at: Pt,
  connects: string[],
  doorType: string,
  state: string,
  facing: string,
  trapped = false,
): string {
  const lines: string[] = [];
  if (connects.length) lines.push(`  connects ${connects.join(", ")}`);
  lines.push(`  type ${doorType}`);
  // arch / open are stateless (no leaf to be open/closed/locked).
  if (doorType !== "arch" && doorType !== "open") lines.push(`  state ${state}`);
  if (facing && facing !== "auto") lines.push(`  facing ${facing}`);
  if (trapped) lines.push(`  trapped`);
  return `\ndoor at ${num(at.x)},${num(at.y)} {\n${lines.join("\n")}\n}\n`;
}
