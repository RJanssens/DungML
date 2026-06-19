// SVG preview with pan, zoom, fit-to-container — plus an optional tracing
// overlay (a reference image under the map) and click-to-draw tools that
// emit .dmap snippets back to the editor.
//
// The server-rendered SVG is inserted via dangerouslySetInnerHTML inside a
// "stage" div that we CSS-transform. A reference <img> and a transparent
// drawing <svg> are siblings inside that same stage, so they pan/zoom in
// lockstep with the map. Zoom anchors on the cursor; drag pans (select tool
// only); double-click + the "Fit" button reset. Keyboard: +/- zoom, 0 fit.
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type WheelEvent,
  type MouseEvent,
  type KeyboardEvent,
} from "react";
import styles from "./SvgPreview.module.css";
import {
  DRAG_TOOLS,
  FEATURE_TOOLS,
  VERTEX_TOOLS,
  dist,
  readMapMeta,
  screenToSvg,
  snapCellCenter,
  snapPt,
  svgToWorld,
  worldToSvg,
  type DraftShape,
  type MapMeta,
  type Pt,
  type Tool,
} from "../lib/draw";

const MIN_RELATIVE = 0.25; // can zoom down to 25% of fit-scale
const MAX_ABSOLUTE = 32; // …and up to 3200% pixel scale
const WHEEL_FACTOR = 1.15;
const KEYBOARD_FACTOR = 1.25;
const CLOSE_DIST = 0.75; // world units: click this near the start to close a polygon

export function SvgPreview({
  svg,
  error,
  loading,
  notice,
  tool = "select",
  snap = true,
  snapResolution = 1,
  bgImage = null,
  bgOpacity = 0.5,
  doorType = "wooden",
  doorState = "closed",
  doorFacing = "auto",
  doorTrapped = false,
  featureType = "pit-trap",
  featureRotate = 0,
  featureScale = 1,
  corridorOrganic = false,
  corridorStraight = false,
  textContent = "",
  textSize = 1,
  areaKind = "water",
  areaOrganic = true,
  lineKind = "bars",
  pathCheck = false,
  connectivity = null,
  onEmit,
  onPick,
}: {
  svg: string | null;
  error?: string | null;
  loading?: boolean;
  /** Informational message shown in place of "No preview yet." — used
   * by the editor to flag library files (which have no map block and
   * therefore intentionally produce no render). */
  notice?: string | null;
  /** Active drawing tool. "select" keeps the pan/zoom behaviour. */
  tool?: Tool;
  /** Snap emitted coordinates to whole world units. */
  snap?: boolean;
  /** Subdivide the snap grid: 1 = whole-cell dots, 2 = twice as many, … */
  snapResolution?: number;
  /** Reference image (data URL) shown under the map for tracing. */
  bgImage?: string | null;
  bgOpacity?: number;
  /** Door properties applied by the "door" tool. */
  doorType?: string;
  doorState?: string;
  doorFacing?: string;
  doorTrapped?: boolean;
  /** Feature tool: which built-in glyph to drop, plus rotation/scale. */
  featureType?: string;
  featureRotate?: number;
  featureScale?: number;
  /** Draw corridors with an organic (wavy) wall style. */
  corridorOrganic?: boolean;
  /** Draw corridors with straight (sharp) corners instead of rounded. */
  corridorStraight?: boolean;
  /** Text tool: the content to place and its font-size multiplier. */
  textContent?: string;
  textSize?: number;
  /** Area tool: terrain kind and whether to give it an organic edge. */
  areaKind?: string;
  areaOrganic?: boolean;
  /** Line-feature tool: which style to draw (bars / curtain / barred). */
  lineKind?: string;
  /** Pathing check: tint each room/corridor by whether a door touches it. */
  pathCheck?: boolean;
  connectivity?: { kind: string; name: string; connected: boolean }[] | null;
  /** Called with a completed shape; the editor turns it into a snippet. */
  onEmit?: (shape: DraftShape) => void;
  /** Select-mode: a click on a room/corridor (jump-to-definition). */
  onPick?: (kind: "room" | "corridor", name: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    tx: number;
    ty: number;
    button: number; // 0 = left (select pan / click), 1 = middle (pan in any mode)
  } | null>(null);

  const [scale, setScale] = useState(1);
  const [fitScale, setFitScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [viewBox, setViewBox] = useState<string | null>(null);
  const [meta, setMeta] = useState<MapMeta | null>(null);
  const [tip, setTip] = useState<
    | { x: number; y: number; title: string; body: string; dmNotes: string }
    | null
  >(null);

  // Drawing state (all points in world coords).
  const [draft, setDraft] = useState<Pt[]>([]);
  const [cursor, setCursor] = useState<Pt | null>(null);
  const [doorHint, setDoorHint] = useState<string[]>([]); // inferred connects under cursor
  // Corridor graph being drawn: a set of nodes, the runs between them, and the
  // node new runs extend from. Clicking an existing node re-points `current`
  // there, which is how branches / junctions are drawn.
  const [corr, setCorr] = useState<{
    nodes: Pt[];
    runs: [number, number][];
    current: number | null;
  }>({ nodes: [], runs: [], current: null });
  const dragStart = useRef<Pt | null>(null);
  // Time/place of the last vertex-adding click, to swallow the second click of
  // a double-click (which would otherwise drop a spurious short end segment).
  const lastDown = useRef<{ t: number; x: number; y: number } | null>(null);

  const drawing = tool !== "select";

  // After every render where the SVG markup changes, measure the underlying
  // <svg> element and recompute the fit scale + center, and capture the map
  // metadata the drawing layer needs.
  useLayoutEffect(() => {
    const host = mapRef.current;
    if (!host) return;
    const inner = host.querySelector("svg");
    if (!inner) {
      setNatural(null);
      setMeta(null);
      setViewBox(null);
      return;
    }
    const w =
      parseFloat(inner.getAttribute("width") ?? "") ||
      inner.viewBox.baseVal.width ||
      inner.getBoundingClientRect().width;
    const h =
      parseFloat(inner.getAttribute("height") ?? "") ||
      inner.viewBox.baseVal.height ||
      inner.getBoundingClientRect().height;
    if (w > 0 && h > 0) {
      setNatural((prev) =>
        prev && prev.w === w && prev.h === h ? prev : { w, h },
      );
    }
    setViewBox(inner.getAttribute("viewBox"));
    setMeta(readMapMeta(inner as SVGSVGElement));
  }, [svg]);

  // Pathing check: tint each room floor (fill) / corridor floor (stroke) green
  // if a door touches it, red if not. Mutates the injected SVG in place; reset
  // whenever the SVG, the toggle, or the connectivity data changes.
  useLayoutEffect(() => {
    const root = mapRef.current?.querySelector("svg");
    if (!root) return;
    root.querySelectorAll("[data-pathtint]").forEach((el) => {
      const e = el as SVGElement;
      e.style.fill = "";
      e.style.stroke = "";
      e.removeAttribute("data-pathtint");
    });
    root.querySelector("#dungml-pathtint-style")?.remove();
    if (!pathCheck || !connectivity) return;
    const status = new Map(
      connectivity.map((n) => [`${n.kind}.${n.name}`, n.connected]),
    );
    const GREEN = "rgba(34, 160, 90, 0.55)";
    const RED = "rgba(206, 52, 38, 0.6)";
    root.querySelectorAll("[data-room],[data-corridor]").forEach((el) => {
      const e = el as SVGElement;
      const room = e.getAttribute("data-room");
      const ok = status.get(room ? `room.${room}` : `corridor.${e.getAttribute("data-corridor")}`);
      if (ok === undefined) return;
      const color = ok ? GREEN : RED;
      const cls = e.getAttribute("class") ?? "";
      if (cls === "floor") {
        e.style.fill = color;
        e.setAttribute("data-pathtint", "1");
      } else if (cls.includes("corridor-floor")) {
        e.style.stroke = color;
        e.setAttribute("data-pathtint", "1");
      }
    });
    // Recolor doors a distinct blue so it's easy to confirm each wall has one.
    // A class rule beats the door-leaf's `fill="#111"` presentation attribute.
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.id = "dungml-pathtint-style";
    style.textContent =
      ".door,.door-swing,.secret-door{stroke:#1763c9 !important}" +
      ".door-leaf{fill:#1763c9 !important}";
    root.appendChild(style);
  }, [svg, pathCheck, connectivity]);

  // Recompute fit scale + translate whenever natural or container size changes.
  const fit = useCallback(() => {
    const container = containerRef.current;
    if (!container || !natural) return;
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (cw <= 0 || ch <= 0) return;
    const pad = 0.94;
    const s = Math.min(cw / natural.w, ch / natural.h) * pad;
    setFitScale(s);
    setScale(s);
    setTx((cw - natural.w * s) / 2);
    setTy((ch - natural.h * s) / 2);
  }, [natural]);

  useLayoutEffect(() => {
    fit();
  }, [fit]);

  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(c);
    return () => ro.disconnect();
  }, [fit]);

  // Abandon any in-progress drawing when the tool changes.
  useEffect(() => {
    setDraft([]);
    setCursor(null);
    setDoorHint([]);
    setCorr({ nodes: [], runs: [], current: null });
    dragStart.current = null;
  }, [tool]);

  // --- zoom helpers ---

  const minScale = useMemo(
    () => Math.max(0.01, fitScale * MIN_RELATIVE),
    [fitScale],
  );

  const clampScale = useCallback(
    (s: number) => Math.max(minScale, Math.min(MAX_ABSOLUTE, s)),
    [minScale],
  );

  const zoomAt = useCallback(
    (cx: number, cy: number, factor: number) => {
      setScale((current) => {
        const next = clampScale(current * factor);
        const ratio = next / current;
        setTx((t) => cx - (cx - t) * ratio);
        setTy((t) => cy - (cy - t) * ratio);
        return next;
      });
    },
    [clampScale],
  );

  // --- drawing helpers ---

  const mapSvg = useCallback(
    () => mapRef.current?.querySelector("svg") as SVGSVGElement | null,
    [],
  );

  const worldFromEvent = useCallback(
    (clientX: number, clientY: number): Pt | null => {
      const el = mapSvg();
      if (!el || !meta) return null;
      const world = svgToWorld(screenToSvg(el, clientX, clientY), meta);
      // Single-cell features sit at cell centres; corridors and doors snap on a
      // double-resolution (half-cell) grid; rooms snap to whole cells. The
      // snap resolution subdivides that further (2 = twice as many dots, …).
      if (FEATURE_TOOLS.has(tool))
        return snapCellCenter(world, snap, snapResolution);
      const base = tool === "corridor" || tool === "door" ? 0.5 : 1;
      const step = base / Math.max(1, snapResolution);
      return snapPt(world, snap, step);
    },
    [mapSvg, meta, snap, snapResolution, tool],
  );

  // Which room/corridor (if any) covers a world point — read off the rendered
  // SVG's data-room / data-corridor attributes via document hit-testing. The
  // tracing/draw overlays are pointer-events:none, so they're skipped.
  const regionAt = useCallback(
    (w: Pt): string | null => {
      const el = mapSvg();
      if (!el || !meta) return null;
      const rect = el.getBoundingClientRect();
      const vb = el.viewBox.baseVal;
      const sp = worldToSvg(w, meta);
      const sx = rect.left + (sp.x / vb.width) * rect.width;
      const sy = rect.top + (sp.y / vb.height) * rect.height;
      for (const e of document.elementsFromPoint(sx, sy)) {
        const r = e.getAttribute("data-room");
        if (r) return `room.${r}`;
        const c = e.getAttribute("data-corridor");
        if (c) return `corridor.${c}`;
      }
      return null;
    },
    [mapSvg, meta],
  );

  // A door sits on a wall between (up to) two regions: probe a little to each
  // side and collect the distinct regions found. One region → an exterior
  // door; none → leave connects off (the user can fill it in).
  const inferConnects = useCallback(
    (w: Pt): string[] => {
      const D = 0.7;
      const probes: Pt[] = [
        { x: w.x - D, y: w.y },
        { x: w.x + D, y: w.y },
        { x: w.x, y: w.y - D },
        { x: w.x, y: w.y + D },
      ];
      const ids: string[] = [];
      for (const p of probes) {
        const id = regionAt(p);
        if (id && !ids.includes(id)) ids.push(id);
        if (ids.length === 2) break;
      }
      return ids;
    },
    [regionAt],
  );

  const finishVertexShape = useCallback(
    (pts: Pt[]) => {
      if (tool === "line") {
        // An open polyline — two points is the minimum (a single segment).
        if (pts.length >= 2)
          onEmit?.({ kind: "lineFeature", pts, lineKind });
      } else if (pts.length >= 3) {
        if (tool === "area")
          onEmit?.({ kind: "area", pts, areaKind, organic: areaOrganic });
        else onEmit?.({ kind: tool === "cave" ? "cave" : "polygon", pts });
      }
      setDraft([]);
      setCursor(null);
    },
    [tool, onEmit, areaKind, areaOrganic, lineKind],
  );

  const finishCorridor = useCallback(() => {
    setCorr((c) => {
      if (c.runs.length >= 1)
        onEmit?.({
          kind: "corridor",
          nodes: c.nodes,
          runs: c.runs,
          organic: corridorOrganic,
          straight: corridorStraight,
        });
      return { nodes: [], runs: [], current: null };
    });
    setCursor(null);
  }, [onEmit, corridorOrganic, corridorStraight]);

  // --- event handlers ---

  function onWheel(e: WheelEvent<HTMLDivElement>) {
    if (e.ctrlKey || e.metaKey || !e.shiftKey) {
      e.preventDefault();
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? WHEEL_FACTOR : 1 / WHEEL_FACTOR;
      zoomAt(cx, cy, factor);
    }
  }

  function onMouseDown(e: MouseEvent<HTMLDivElement>) {
    // Middle button pans in every mode (drawing or select).
    if (e.button === 1) {
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        tx,
        ty,
        button: 1,
      };
      return;
    }
    if (e.button !== 0) return;
    if (drawing) {
      const w = worldFromEvent(e.clientX, e.clientY);
      if (!w) return;
      e.preventDefault();
      // For the multi-click tools, ignore the second click of a double-click
      // (the finish gesture) so it can't add a stray short segment.
      if (tool === "corridor" || VERTEX_TOOLS.has(tool)) {
        const ld = lastDown.current;
        const rapid =
          !!ld &&
          e.timeStamp - ld.t < 350 &&
          Math.hypot(e.clientX - ld.x, e.clientY - ld.y) < 6;
        lastDown.current = { t: e.timeStamp, x: e.clientX, y: e.clientY };
        if (rapid) return;
      }
      if (tool === "door") {
        onEmit?.({
          kind: "door",
          at: w,
          connects: inferConnects(w),
          doorType,
          state: doorState,
          facing: doorFacing,
          trapped: doorTrapped,
        });
      } else if (FEATURE_TOOLS.has(tool)) {
        onEmit?.({
          kind: "feature",
          at: w,
          ref: featureType,
          rotate: featureRotate,
          scale: featureScale,
        });
      } else if (tool === "text") {
        // Use the toolbar's text if set; otherwise prompt so a click always
        // does something (rather than silently no-op on an empty field).
        const preset = textContent.trim();
        const content = (preset || window.prompt("Text to place:", "") || "").trim();
        if (content) onEmit?.({ kind: "text", at: w, content, size: textSize });
      } else if (DRAG_TOOLS.has(tool)) {
        dragStart.current = w;
        setDraft([w]);
        setCursor(w);
      } else if (tool === "corridor") {
        // Click an existing node → make it current (start a branch from it);
        // click empty → add a node and a run from the current node.
        setCorr((c) => {
          const k = c.nodes.findIndex((n) => dist(n, w) < 1e-6);
          if (k >= 0) return { ...c, current: k };
          const nodes = [...c.nodes, w];
          const m = nodes.length - 1;
          const runs: [number, number][] =
            c.current != null ? [...c.runs, [c.current, m]] : c.runs;
          return { nodes, runs, current: m };
        });
        setCursor(w);
      } else if (
        VERTEX_TOOLS.has(tool) &&
        draft.length >= 3 &&
        dist(w, draft[0]) < CLOSE_DIST
      ) {
        finishVertexShape(draft);
      } else if (draft.length && dist(w, draft[draft.length - 1]) < 1e-6) {
        setCursor(w); // ignore the duplicate click that precedes a double-click
      } else {
        setDraft([...draft, w]);
        setCursor(w);
      }
      return;
    }
    dragRef.current = { startX: e.clientX, startY: e.clientY, tx, ty, button: 0 };
  }

  function onMouseMove(e: MouseEvent<HTMLDivElement>) {
    // Panning (middle button anywhere, or left button in select mode).
    const pan = dragRef.current;
    if (pan) {
      setTx(pan.tx + (e.clientX - pan.startX));
      setTy(pan.ty + (e.clientY - pan.startY));
      return;
    }
    if (drawing) {
      const w = worldFromEvent(e.clientX, e.clientY);
      if (w) {
        setCursor(w);
        if (tool === "door") setDoorHint(inferConnects(w));
      }
      return;
    }
    // Hover-tooltip (select mode only).
    const target = e.target as Element | null;
    const el = target?.closest(
      "[data-description],[data-label],[data-ref],[data-room],[data-corridor],[data-dm-notes]",
    ) as Element | null;
    if (el) {
      const body = el.getAttribute("data-description") ?? "";
      const dmNotes = el.getAttribute("data-dm-notes") ?? "";
      const title =
        el.getAttribute("data-label") ??
        el.getAttribute("data-ref") ??
        el.getAttribute("data-room") ??
        el.getAttribute("data-corridor") ??
        "";
      if (title || body || dmNotes) {
        setTip({ x: e.clientX, y: e.clientY, title, body, dmNotes });
      } else if (tip) {
        setTip(null);
      }
    } else if (tip) {
      setTip(null);
    }
  }

  function onMouseUp(e: MouseEvent<HTMLDivElement>) {
    // End a pan. A left-button (select) pan that barely moved is a click →
    // jump to the clicked room/corridor's definition. Middle-button pans never
    // pick.
    const pan = dragRef.current;
    if (pan) {
      dragRef.current = null;
      if (
        pan.button === 0 &&
        onPick &&
        Math.hypot(e.clientX - pan.startX, e.clientY - pan.startY) < 4
      ) {
        // Hit-test by point, not e.target: pointer capture on the host can
        // retarget mouseup to the container, hiding the clicked room.
        const el = document
          .elementFromPoint(e.clientX, e.clientY)
          ?.closest("[data-room],[data-corridor]");
        if (el) {
          const room = el.getAttribute("data-room");
          const corr = el.getAttribute("data-corridor");
          if (room) onPick("room", room);
          else if (corr) onPick("corridor", corr);
        }
      }
      return;
    }
    if (drawing) {
      if (DRAG_TOOLS.has(tool) && dragStart.current) {
        const a = dragStart.current;
        const b = worldFromEvent(e.clientX, e.clientY) ?? cursor ?? a;
        dragStart.current = null;
        if (dist(a, b) > 0.001) {
          if (tool === "rect") onEmit?.({ kind: "rect", a, b });
          else if (tool === "circle")
            onEmit?.({ kind: "circle", center: a, edge: b });
        }
        setDraft([]);
        setCursor(null);
      }
    }
  }

  function onMouseLeaveHost() {
    dragRef.current = null;
    setTip(null);
  }

  function onDoubleClick() {
    if (drawing) {
      if (tool === "corridor") finishCorridor();
      else if (VERTEX_TOOLS.has(tool)) finishVertexShape(draft);
      return;
    }
    fit();
  }

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (drawing && (e.key === "Enter" || e.key === "Escape")) {
      e.preventDefault();
      if (e.key === "Enter") {
        if (tool === "corridor") finishCorridor();
        else if (VERTEX_TOOLS.has(tool)) finishVertexShape(draft);
      } else {
        setDraft([]);
        setCursor(null);
        setCorr({ nodes: [], runs: [], current: null });
        dragStart.current = null;
      }
      return;
    }
    const rect = containerRef.current?.getBoundingClientRect();
    const cx = rect ? rect.width / 2 : 0;
    const cy = rect ? rect.height / 2 : 0;
    if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      zoomAt(cx, cy, KEYBOARD_FACTOR);
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      zoomAt(cx, cy, 1 / KEYBOARD_FACTOR);
    } else if (e.key === "0") {
      e.preventDefault();
      fit();
    }
  }

  const showOverlay = svg !== null && !error;
  const zoomPct = Math.round((scale / fitScale) * 100);

  return (
    <div className={styles.wrap}>
      <div
        ref={containerRef}
        className={`${styles.stageHost} ${drawing ? styles.drawing : ""}`}
        tabIndex={0}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeaveHost}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKey}
        role="presentation"
      >
        {loading && svg === null ? (
          <div className={styles.placeholder}>Rendering…</div>
        ) : error && !svg ? (
          <div className={styles.errorBox}>
            <div className={styles.errorTitle}>Cannot render</div>
            <div className={styles.errorDetail}>{error}</div>
          </div>
        ) : svg ? (
          <div
            ref={stageRef}
            className={`${styles.stage} ${error ? styles.stale : ""}`}
            style={{
              transform: `translate3d(${tx}px, ${ty}px, 0) scale(${scale})`,
            }}
          >
            {bgImage && natural ? (
              <img
                className={styles.bgLayer}
                src={bgImage}
                alt=""
                draggable={false}
                style={{
                  width: natural.w,
                  height: natural.h,
                  opacity: bgOpacity,
                }}
              />
            ) : null}
            <div
              ref={mapRef}
              className={styles.mapLayer}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
            {natural && viewBox ? (
              <svg
                className={styles.drawLayer}
                width={natural.w}
                height={natural.h}
                viewBox={viewBox}
              >
                {meta ? renderDraft(tool, draft, corr, cursor, meta) : null}
              </svg>
            ) : null}
          </div>
        ) : notice ? (
          <div className={styles.placeholder}>{notice}</div>
        ) : (
          <div className={styles.placeholder}>No preview yet.</div>
        )}
      </div>
      {showOverlay ? (
        <div className={styles.controls}>
          {drawing && cursor ? (
            <span className={styles.coordReadout} title="Cursor (world units)">
              {cursor.x}, {cursor.y}
              {tool === "door"
                ? ` → ${doorHint.length ? doorHint.join(" · ") : "exterior"}`
                : ""}
            </span>
          ) : null}
          <button
            type="button"
            className={styles.ctrlBtn}
            onClick={() => {
              const r = containerRef.current?.getBoundingClientRect();
              if (r) zoomAt(r.width / 2, r.height / 2, KEYBOARD_FACTOR);
            }}
            title="Zoom in (+)"
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            className={styles.ctrlBtn}
            onClick={() => {
              const r = containerRef.current?.getBoundingClientRect();
              if (r) zoomAt(r.width / 2, r.height / 2, 1 / KEYBOARD_FACTOR);
            }}
            title="Zoom out (-)"
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            className={styles.ctrlBtn}
            onClick={fit}
            title="Fit to view (0)"
            aria-label="Fit to view"
          >
            ⤢
          </button>
          <span className={styles.zoomReadout} title="Zoom level">
            {zoomPct}%
          </span>
        </div>
      ) : null}
      {tip ? (
        <div
          className={styles.tooltip}
          style={{ left: tip.x + 14, top: tip.y + 14 }}
          role="tooltip"
        >
          {tip.title ? (
            <div className={styles.tooltipTitle}>{tip.title}</div>
          ) : null}
          {tip.body ? (
            <div className={styles.tooltipBody}>{tip.body}</div>
          ) : null}
          {tip.dmNotes ? (
            <div className={styles.tooltipDm}>
              <span className={styles.tooltipDmLabel}>DM</span>
              <span>{tip.dmNotes}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Live preview of the shape being drawn, in SVG/world space.
function renderDraft(
  tool: Tool,
  draft: Pt[],
  corr: { nodes: Pt[]; runs: [number, number][]; current: number | null },
  cursor: Pt | null,
  meta: MapMeta,
) {
  const s = (p: Pt) => worldToSvg(p, meta);
  const dot = (p: Pt, key: string) => {
    const q = s(p);
    return <circle key={key} cx={q.x} cy={q.y} r={0.3} className={styles.dDot} />;
  };

  // Corridor: the run graph so far, a rubber band from the active node to the
  // cursor, and a dot per node (the active one — what a new run extends from —
  // drawn larger).
  if (tool === "corridor") {
    const runs = corr.runs.map(([i, j], idx) => {
      const a = s(corr.nodes[i]);
      const b = s(corr.nodes[j]);
      return (
        <line
          key={`r${idx}`}
          className={styles.dLine}
          x1={a.x}
          y1={a.y}
          x2={b.x}
          y2={b.y}
        />
      );
    });
    let band = null;
    if (corr.current != null && cursor) {
      const a = s(corr.nodes[corr.current]);
      const b = s(cursor);
      band = (
        <line
          className={styles.dLine}
          x1={a.x}
          y1={a.y}
          x2={b.x}
          y2={b.y}
          strokeOpacity={0.5}
        />
      );
    }
    const dots = corr.nodes.map((p, i) => {
      const q = s(p);
      const isCur = i === corr.current;
      return (
        <circle
          key={`n${i}`}
          cx={q.x}
          cy={q.y}
          r={isCur ? 0.45 : 0.3}
          className={isCur ? styles.dDotActive : styles.dDot}
        />
      );
    });
    return (
      <g>
        {runs}
        {band}
        {dots}
      </g>
    );
  }

  // Text: a small dot marking where the text will be anchored.
  if (tool === "text") {
    if (!cursor) return null;
    return dot(cursor, "text-cursor");
  }

  // Door / single-cell feature: a 1-unit marker at the cursor cell.
  if (tool === "door" || FEATURE_TOOLS.has(tool)) {
    if (!cursor) return null;
    const q = s(cursor);
    return (
      <rect
        className={styles.dShape}
        x={q.x - 0.5}
        y={q.y - 0.5}
        width={1}
        height={1}
      />
    );
  }

  if (DRAG_TOOLS.has(tool)) {
    if (!draft.length || !cursor) return null;
    const a = s(draft[0]);
    const b = s(cursor);
    if (tool === "rect") {
      return (
        <rect
          className={styles.dShape}
          x={Math.min(a.x, b.x)}
          y={Math.min(a.y, b.y)}
          width={Math.abs(b.x - a.x)}
          height={Math.abs(b.y - a.y)}
        />
      );
    }
    return (
      <circle
        className={styles.dShape}
        cx={a.x}
        cy={a.y}
        r={Math.hypot(b.x - a.x, b.y - a.y)}
      />
    );
  }

  // Vertex tools: the placed points plus a rubber band to the cursor. The
  // line-feature tool is an open polyline; the rest close into a polygon.
  if (!draft.length) return null;
  const pts = cursor ? [...draft, cursor] : draft;
  const ptsStr = pts.map((p) => { const q = s(p); return `${q.x},${q.y}`; }).join(" ");
  return (
    <g>
      {tool === "line" ? (
        <polyline className={styles.dShape} points={ptsStr} fill="none" />
      ) : (
        <polygon className={styles.dShape} points={ptsStr} />
      )}
      {draft.map((p, i) => dot(p, `v${i}`))}
    </g>
  );
}
