import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import type {
  Diagnostic,
  NodeConnectivity,
  RenderResponse,
} from "../lib/types";
import { useDebounce } from "../lib/useDebounce";
import { Button } from "../components/Primitives";
import { AppHeader, PageShell } from "../components/Layout";
import { MonacoEditor } from "../components/MonacoEditor";
import { SvgPreview } from "../components/SvgPreview";
import { DrawToolbar } from "../components/DrawToolbar";
import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import {
  emitShape,
  findDefinition,
  hasCellGrid,
  insertFeatureInRegion,
  setCellGrid,
  sortSource,
  type DraftShape,
  type Tool,
} from "../lib/draw";
import styles from "./MapEditor.module.css";

export function MapEditorPage() {
  const { mapId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: map, isLoading } = useQuery({
    queryKey: ["map", mapId],
    queryFn: () => api.maps.get(mapId),
    enabled: !!mapId,
  });

  // Sibling maps in this project — the destinations the exit tool can target
  // (other renderable maps; library files and this map itself are excluded).
  const { data: projectMaps = [] } = useQuery({
    queryKey: ["maps", map?.project_id ?? ""],
    queryFn: () => api.maps.list(map?.project_id ?? ""),
    enabled: !!map?.project_id,
  });
  const exitMapOptions = projectMaps
    .filter((m) => m.kind !== "library" && m.id !== mapId)
    .map((m) => m.name);

  const [source, setSource] = useState<string>("");
  const [lastSaved, setLastSaved] = useState<string>("");
  // Initialize editor contents when the map loads (or changes).
  useEffect(() => {
    if (map) {
      setSource(map.source);
      setLastSaved(map.source);
    }
  }, [map]);

  const dirty = source !== lastSaved;

  // --- drawing tools + tracing reference (editor-only, never saved to .dmap) ---
  const [tool, setTool] = useState<Tool>("select");
  const [snap, setSnap] = useState(true);
  const [snapResolution, setSnapResolution] = useState(1);
  const [bgImage, setBgImage] = useState<string | null>(null);
  const [bgOpacity, setBgOpacity] = useState(0.5);
  const [doorType, setDoorType] = useState("wooden");
  const [doorState, setDoorState] = useState("closed");
  const [doorFacing, setDoorFacing] = useState("auto");
  const [doorTrapped, setDoorTrapped] = useState(false);
  const [featureType, setFeatureType] = useState("pit-trap");
  const [featureRotate, setFeatureRotate] = useState(0);
  const [featureScale, setFeatureScale] = useState(1);
  const [featureGlobal, setFeatureGlobal] = useState(false);
  // Feature types available to this map — the feature_defs its includes
  // resolve to (plus any defined locally). `featureTypes` is the flat list
  // (for default-selection); `featureGroups` splits them by source file for
  // the grouped dropdown. Populated from the backend.
  const [featureTypes, setFeatureTypes] = useState<string[]>([]);
  const [featureGroups, setFeatureGroups] = useState<api.FeatureGroup[]>([]);
  const [corridorOrganic, setCorridorOrganic] = useState(false);
  const [corridorStraight, setCorridorStraight] = useState(false);
  const [textContent, setTextContent] = useState("");
  const [textSize, setTextSize] = useState(1);
  const [areaKind, setAreaKind] = useState("water");
  const [areaOrganic, setAreaOrganic] = useState(true);
  const [lineKind, setLineKind] = useState("bars");
  const [exitTargetMap, setExitTargetMap] = useState("");
  const [exitTargetX, setExitTargetX] = useState(0);
  const [exitTargetY, setExitTargetY] = useState(0);
  const [exitLabel, setExitLabel] = useState("");
  const [exitSecret, setExitSecret] = useState(false);
  const [pathCheck, setPathCheck] = useState(false);
  const [connectionsMode, setConnectionsMode] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // Draggable split between the editor and the preview (editor width %).
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [splitPct, setSplitPct] = useState<number>(() => {
    const v = Number(localStorage.getItem("dungml.split"));
    return v >= 15 && v <= 85 ? v : 50;
  });
  useEffect(() => {
    try {
      localStorage.setItem("dungml.split", String(Math.round(splitPct)));
    } catch {
      /* storage unavailable */
    }
  }, [splitPct]);
  function startSplitDrag(e: ReactMouseEvent) {
    e.preventDefault();
    const move = (ev: MouseEvent) => {
      const el = workspaceRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const pct = ((ev.clientX - r.left) / r.width) * 100;
      setSplitPct(Math.min(85, Math.max(15, pct)));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }
  const [connectivity, setConnectivity] = useState<NodeConnectivity[] | null>(
    null,
  );
  const traceKey = mapId ? `dungml.trace.${mapId}` : "";

  // Load any saved tracing reference for this map from the browser.
  useEffect(() => {
    if (!traceKey) return;
    setBgImage(null);
    setBgOpacity(0.5);
    try {
      const raw = localStorage.getItem(traceKey);
      if (raw) {
        const v = JSON.parse(raw) as { image?: string; opacity?: number };
        if (v.image) setBgImage(v.image);
        if (typeof v.opacity === "number") setBgOpacity(v.opacity);
      }
    } catch {
      /* ignore malformed/unavailable storage */
    }
  }, [traceKey]);

  // Persist the reference per-map (best-effort — a large image may exceed the
  // storage quota, in which case it simply stays in-session).
  useEffect(() => {
    if (!traceKey) return;
    try {
      if (bgImage) {
        localStorage.setItem(
          traceKey,
          JSON.stringify({ image: bgImage, opacity: bgOpacity }),
        );
      } else {
        localStorage.removeItem(traceKey);
      }
    } catch {
      /* quota exceeded or storage disabled — overlay still works this session */
    }
  }, [traceKey, bgImage, bgOpacity]);

  // A completed shape becomes a .dmap block appended to the source. A feature
  // dropped on a room/corridor is nested inside that block instead (the preview
  // sets `region`); if the block can't be located we fall back to appending.
  const onEmit = useCallback((shape: DraftShape) => {
    setSource((s) => {
      if (shape.kind === "feature" && shape.region) {
        const nested = insertFeatureInRegion(
          s,
          shape.region,
          shape.at,
          shape.ref,
          shape.rotate ?? 0,
          shape.scale ?? 1,
        );
        if (nested) return nested;
      }
      return s + emitShape(s, shape);
    });
  }, []);

  // Jump-to-definition: reveal a line in the editor (nonce forces re-trigger).
  const [goto, setGoto] = useState<{
    line: number;
    column: number;
    nonce: number;
  } | null>(null);

  const onPick = useCallback(
    (kind: "room" | "corridor", name: string) => {
      // Connections mode: clicking a node lists its doors. Otherwise jump to
      // the node's definition in the editor.
      if (connectionsMode) {
        setSelectedNode(`${kind}.${name}`);
        return;
      }
      const def = findDefinition(source, kind, name);
      if (def) setGoto((g) => ({ ...def, nonce: (g?.nonce ?? 0) + 1 }));
    },
    [source, connectionsMode],
  );

  const onJump = useCallback((d: Diagnostic) => {
    if (d.line > 0)
      setGoto((g) => ({
        line: d.line,
        column: Math.max(1, d.column),
        nonce: (g?.nonce ?? 0) + 1,
      }));
  }, []);

  // Live preview — debounced render call against /api/maps/{id}/render so
  // `include "core.dmap"` resolves to the project's own editable copy.
  const debouncedSource = useDebounce(source, 350);
  const [preview, setPreview] = useState<RenderResponse | null>(null);
  const [renderError, setRenderError] = useState<{
    message: string;
    line?: number;
    column?: number;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const renderSeq = useRef(0);

  // Library files (no top-level `map "..." { }` block) are not
  // renderable — they're included by other maps. Detect early and skip
  // the render call so the editor doesn't keep flashing a parse error.
  const isLibrary = !/\bmap\s+"/.test(debouncedSource);

  useEffect(() => {
    if (!debouncedSource) {
      setPreview(null);
      setRenderError(null);
      return;
    }
    if (isLibrary) {
      setPreview(null);
      setRenderError(null);
      setPreviewLoading(false);
      return;
    }
    const seq = ++renderSeq.current;
    setPreviewLoading(true);
    api.maps
      .render(mapId, debouncedSource)
      .then((r) => {
        if (seq !== renderSeq.current) return;
        setPreview(r);
        setRenderError(null);
      })
      .catch((e) => {
        if (seq !== renderSeq.current) return;
        if (e instanceof ApiError && typeof e.detail === "object" && e.detail) {
          const d = e.detail as {
            detail?: { message?: string; line?: number; column?: number };
          };
          const inner = d.detail ?? {};
          setRenderError({
            message: inner.message ?? e.message,
            line: inner.line,
            column: inner.column,
          });
        } else {
          setRenderError({ message: String(e?.message ?? e) });
        }
      })
      .finally(() => {
        if (seq === renderSeq.current) setPreviewLoading(false);
      });
  }, [debouncedSource, mapId]);

  // Available feature types for the dropdown — refreshed when the source
  // changes (e.g. an `include` is added/removed). Keeps the last good list
  // on parse errors so the dropdown doesn't flicker empty mid-edit.
  useEffect(() => {
    if (!mapId || !debouncedSource) return;
    let cancelled = false;
    api.maps
      .featureNames(mapId, debouncedSource)
      .then((r) => {
        if (cancelled || r.names.length === 0) return;
        setFeatureTypes(r.names);
        setFeatureGroups(r.groups);
        // If the current pick is no longer offered, snap to the first.
        setFeatureType((cur) => (r.names.includes(cur) ? cur : r.names[0]));
      })
      .catch(() => {
        /* keep the last good list */
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSource, mapId]);

  // Fetch per-node connectivity while pathing-check or connections mode is on.
  useEffect(() => {
    if ((!pathCheck && !connectionsMode) || !debouncedSource || isLibrary) {
      setConnectivity(null);
      return;
    }
    let cancelled = false;
    api.dsl
      .connectivity(debouncedSource)
      .then((r) => {
        if (!cancelled) setConnectivity(r.nodes);
      })
      .catch(() => {
        if (!cancelled) setConnectivity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathCheck, connectionsMode, debouncedSource, isLibrary]);

  // Diagnostics shown in the panel come from a successful render. On a
  // parse error we synthesize a single error diagnostic so the user
  // still sees the squiggle and the message in the panel.
  const diagnostics: Diagnostic[] = renderError
    ? [
        {
          severity: "error",
          message: renderError.message,
          line: renderError.line ?? 0,
          column: renderError.column ?? 0,
          end_line: renderError.line ?? 0,
          end_column: (renderError.column ?? 0) + 1,
        },
      ]
    : preview?.diagnostics ?? [];

  // Save mutation — explicit save action, not autosave.
  const save = useMutation({
    mutationFn: () => api.maps.update(mapId, { source }),
    onSuccess: (m) => {
      setLastSaved(m.source);
      qc.invalidateQueries({ queryKey: ["map", mapId] });
      qc.invalidateQueries({
        queryKey: ["maps", map?.project_id ?? ""],
        exact: false,
      });
    },
  });

  // Cmd/Ctrl+S: triggered either from inside Monaco (it has its own
  // command binding) or from the document when focus is elsewhere.
  const onSave = useCallback(() => {
    if (!dirty || save.isPending) return;
    save.mutate();
  }, [dirty, save]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        onSave();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSave]);

  // Warn before unloading the tab with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  function downloadSvg() {
    const svg = preview?.svg;
    if (!svg) return;
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${map?.name ?? "map"}.svg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (isLoading || !map) {
    return (
      <PageShell>
        <AppHeader />
        <div className={styles.loadingState}>Loading…</div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <AppHeader
        right={
          <>
            <Link to={`/projects/${map.project_id}`} className={styles.crumb}>
              Project
            </Link>
            <span className={styles.crumbSep}>/</span>
            <span className={styles.mapName}>{map.name}</span>
            {dirty ? (
              <span className={styles.dirty} title="Unsaved changes">
                ●
              </span>
            ) : null}
            <div className={styles.headerActions}>
              <Button
                variant="ghost"
                disabled={dirty}
                onClick={() => navigate(`/maps/${mapId}/play`)}
                title={
                  dirty
                    ? "Save first — the play view reads the stored map."
                    : "Open fog-of-war play view"
                }
              >
                Play
              </Button>
              <Button
                variant="ghost"
                disabled={dirty}
                onClick={() => navigate(`/maps/${mapId}/print`)}
                title={
                  dirty
                    ? "Save first — the print view reads the stored map."
                    : "Open print/PDF view"
                }
              >
                Print
              </Button>
              <Button
                variant="secondary"
                disabled={!preview?.svg}
                onClick={downloadSvg}
              >
                Download SVG
              </Button>
              <Button onClick={onSave} disabled={!dirty || save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </>
        }
      />
      <div
        className={styles.workspace}
        ref={workspaceRef}
        style={{ gridTemplateColumns: `${splitPct}% 6px minmax(0, 1fr)` }}
      >
        <div className={styles.editorPane}>
          <div className={styles.editorBox}>
            <MonacoEditor
              value={source}
              onChange={setSource}
              diagnostics={diagnostics}
              onSave={onSave}
              goto={goto}
            />
          </div>
          <DiagnosticsPanel diagnostics={diagnostics} onJump={onJump} />
        </div>
        <div
          className={styles.divider}
          onMouseDown={startSplitDrag}
          onDoubleClick={() => setSplitPct(50)}
          role="separator"
          aria-orientation="vertical"
          title="Drag to resize · double-click to reset"
        />
        <div className={styles.previewPane}>
          <DrawToolbar
            tool={tool}
            onTool={setTool}
            snap={snap}
            onSnap={setSnap}
            snapResolution={snapResolution}
            onSnapResolution={setSnapResolution}
            bgImage={bgImage}
            onBgImage={setBgImage}
            bgOpacity={bgOpacity}
            onBgOpacity={setBgOpacity}
            doorType={doorType}
            onDoorType={setDoorType}
            doorState={doorState}
            onDoorState={setDoorState}
            doorFacing={doorFacing}
            onDoorFacing={setDoorFacing}
            doorTrapped={doorTrapped}
            onDoorTrapped={setDoorTrapped}
            featureType={featureType}
            onFeatureType={setFeatureType}
            featureTypes={featureTypes}
            featureGroups={featureGroups}
            featureRotate={featureRotate}
            onFeatureRotate={setFeatureRotate}
            featureScale={featureScale}
            onFeatureScale={setFeatureScale}
            featureGlobal={featureGlobal}
            onFeatureGlobal={setFeatureGlobal}
            corridorOrganic={corridorOrganic}
            onCorridorOrganic={setCorridorOrganic}
            corridorStraight={corridorStraight}
            onCorridorStraight={setCorridorStraight}
            textContent={textContent}
            onTextContent={setTextContent}
            textSize={textSize}
            onTextSize={setTextSize}
            areaKind={areaKind}
            onAreaKind={setAreaKind}
            areaOrganic={areaOrganic}
            onAreaOrganic={setAreaOrganic}
            lineKind={lineKind}
            onLineKind={setLineKind}
            exitTargetMap={exitTargetMap}
            onExitTargetMap={setExitTargetMap}
            exitMapOptions={exitMapOptions}
            exitTargetX={exitTargetX}
            onExitTargetX={setExitTargetX}
            exitTargetY={exitTargetY}
            onExitTargetY={setExitTargetY}
            exitLabel={exitLabel}
            onExitLabel={setExitLabel}
            exitSecret={exitSecret}
            onExitSecret={setExitSecret}
            pathCheck={pathCheck}
            onPathCheck={setPathCheck}
            connectionsMode={connectionsMode}
            onConnectionsMode={(v) => {
              setConnectionsMode(v);
              if (!v) setSelectedNode(null);
            }}
            cellGrid={hasCellGrid(source)}
            onCellGrid={(v) => setSource((s) => setCellGrid(s, v))}
            onSort={() => setSource((s) => sortSource(s))}
            disabled={isLibrary}
          />
          <div className={styles.previewArea}>
            <SvgPreview
              svg={preview?.svg ?? null}
              error={renderError?.message ?? null}
              loading={previewLoading}
              tool={tool}
              snap={snap}
              snapResolution={snapResolution}
              bgImage={bgImage}
              bgOpacity={bgOpacity}
              doorType={doorType}
              doorState={doorState}
              doorFacing={doorFacing}
              doorTrapped={doorTrapped}
              featureType={featureType}
              featureRotate={featureRotate}
              featureScale={featureScale}
              featureGlobal={featureGlobal}
              corridorOrganic={corridorOrganic}
              corridorStraight={corridorStraight}
              textContent={textContent}
              textSize={textSize}
              areaKind={areaKind}
              areaOrganic={areaOrganic}
              lineKind={lineKind}
              exitTargetMap={exitTargetMap}
              exitTargetX={exitTargetX}
              exitTargetY={exitTargetY}
              exitLabel={exitLabel}
              exitSecret={exitSecret}
              pathCheck={pathCheck}
              connectivity={connectivity}
              onEmit={onEmit}
              onPick={onPick}
              notice={
                isLibrary
                  ? "Library file — include from a map via `include \"…\"`. No preview."
                  : null
              }
            />
            {connectionsMode && selectedNode ? (
              <div className={styles.connPanel}>
                <div className={styles.connHeader}>
                  <span className={styles.connTitle}>{selectedNode}</span>
                  <button
                    type="button"
                    className={styles.connClose}
                    onClick={() => setSelectedNode(null)}
                    aria-label="Close"
                  >
                    ×
                  </button>
                </div>
                {(() => {
                  const node = connectivity?.find((n) => n.id === selectedNode);
                  if (!node) return <div className={styles.connEmpty}>…</div>;
                  if (node.connections.length === 0)
                    return (
                      <div className={styles.connEmpty}>No doors — isolated.</div>
                    );
                  return (
                    <ul className={styles.connList}>
                      {node.connections.map((c, i) => (
                        <li key={i}>
                          <span className={styles.connArrow}>
                            {c.direction === "out"
                              ? "→"
                              : c.direction === "in"
                                ? "←"
                                : "↔"}
                          </span>
                          <span className={styles.connTo}>{c.to}</span>
                          <span className={styles.connMeta}>
                            {c.type}
                            {c.state && c.state !== "closed"
                              ? `, ${c.state}`
                              : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  );
                })()}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </PageShell>
  );
}
