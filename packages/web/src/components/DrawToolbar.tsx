// Toolbar for the map editor's drawing tools and the tracing-reference image.
import { useRef, type ChangeEvent } from "react";
import type { Tool } from "../lib/draw";
import { Icon } from "./icons";
import styles from "./DrawToolbar.module.css";

const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: "select", label: "Select / pan", hint: "Drag to pan, wheel to zoom. Click a room/corridor to jump to its definition." },
  { id: "rect", label: "Rectangle room", hint: "Drag from one corner to the opposite." },
  { id: "circle", label: "Circle room", hint: "Drag from the centre outward to set the radius." },
  { id: "polygon", label: "Polygon room", hint: "Click each corner; double-click (or Enter) to close. Esc cancels." },
  { id: "cave", label: "Cave room", hint: "Like polygon, but walls render with a natural wavy edge (line_style organic). Click corners; double-click / Enter to close." },
  { id: "corridor", label: "Corridor", hint: "Click waypoints to extend; click an existing node to branch a junction from it. Double-click / Enter finishes, Esc cancels. Snaps to half-cells." },
  { id: "door", label: "Door", hint: "Click on a wall to drop a door — the rooms it connects are inferred from position. Set type / state / facing in the toolbar." },
  { id: "feature", label: "Feature", hint: "Click a cell to drop a feature. Pick the type, rotation and scale in the toolbar." },
  { id: "text", label: "Text", hint: "Type the text and pick a size in the toolbar, then click the map to place it at that fixed point." },
  { id: "area", label: "Terrain area", hint: "Pick a kind (water, lava, pit…) in the toolbar, then click each corner of the pool/area; double-click or Enter to close, Esc cancels. Not a room." },
  { id: "line", label: "Line feature", hint: "Pick a style (bars, curtain, barred) in the toolbar, then click each point along the line; double-click or Enter to finish, Esc cancels." },
];

// Built-in terrain kinds for the area tool (mirror the renderer palette).
const AREA_KINDS = ["water", "lava", "pit", "chasm", "mud", "acid", "ice", "blood", "slime", "swamp"];
// Line-feature styles (mirror the renderer): bars=dotted, curtain=wavy, barred=+.
const LINE_KINDS = ["bars", "curtain", "barred"];

const DOOR_TYPES = ["wooden", "open", "double", "one-way", "arch", "gates", "portcullis", "iron", "stone", "secret", "concealed", "smashed"];
const DOOR_STATES = ["closed", "open", "locked"];
const DOOR_FACINGS = ["auto", "north", "south", "east", "west"];

// Fallback feature list shown until the backend reports which feature_defs
// the map's includes actually resolve to (see `featureTypes` prop).
const FALLBACK_FEATURE_TYPES = [
  "pit-trap", "dart-trap", "fire-trap", "portcullis", "pillar", "altar",
  "statue", "fountain", "brazier", "chest", "rubble", "water", "bridge",
  "stairs-up", "stairs-down", "stairs-left", "stairs-right", "stairs-spiral",
].sort((a, b) => a.localeCompare(b));

export function DrawToolbar({
  tool,
  onTool,
  snap,
  onSnap,
  snapResolution,
  onSnapResolution,
  bgImage,
  onBgImage,
  bgOpacity,
  onBgOpacity,
  doorType,
  onDoorType,
  doorState,
  onDoorState,
  doorFacing,
  onDoorFacing,
  doorTrapped,
  onDoorTrapped,
  featureType,
  onFeatureType,
  featureTypes,
  featureGroups,
  featureRotate,
  onFeatureRotate,
  featureScale,
  onFeatureScale,
  corridorOrganic,
  onCorridorOrganic,
  corridorStraight,
  onCorridorStraight,
  textContent,
  onTextContent,
  textSize,
  onTextSize,
  areaKind,
  onAreaKind,
  areaOrganic,
  onAreaOrganic,
  lineKind,
  onLineKind,
  pathCheck,
  onPathCheck,
  connectionsMode,
  onConnectionsMode,
  cellGrid,
  onCellGrid,
  onSort,
  disabled,
}: {
  tool: Tool;
  onTool: (t: Tool) => void;
  snap: boolean;
  onSnap: (s: boolean) => void;
  snapResolution: number;
  onSnapResolution: (n: number) => void;
  bgImage: string | null;
  onBgImage: (img: string | null) => void;
  bgOpacity: number;
  onBgOpacity: (o: number) => void;
  doorType: string;
  onDoorType: (t: string) => void;
  doorState: string;
  onDoorState: (s: string) => void;
  doorFacing: string;
  onDoorFacing: (f: string) => void;
  doorTrapped: boolean;
  onDoorTrapped: (v: boolean) => void;
  featureType: string;
  onFeatureType: (t: string) => void;
  featureTypes: string[];
  featureGroups: { source: string; names: string[] }[];
  featureRotate: number;
  onFeatureRotate: (n: number) => void;
  featureScale: number;
  onFeatureScale: (n: number) => void;
  corridorOrganic: boolean;
  onCorridorOrganic: (v: boolean) => void;
  corridorStraight: boolean;
  onCorridorStraight: (v: boolean) => void;
  textContent: string;
  onTextContent: (v: string) => void;
  textSize: number;
  onTextSize: (n: number) => void;
  areaKind: string;
  onAreaKind: (v: string) => void;
  areaOrganic: boolean;
  onAreaOrganic: (v: boolean) => void;
  lineKind: string;
  onLineKind: (v: string) => void;
  pathCheck: boolean;
  onPathCheck: (p: boolean) => void;
  connectionsMode: boolean;
  onConnectionsMode: (v: boolean) => void;
  cellGrid: boolean;
  onCellGrid: (v: boolean) => void;
  onSort: () => void;
  disabled?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const active = TOOLS.find((t) => t.id === tool) ?? TOOLS[0];
  const features = featureTypes.length ? featureTypes : FALLBACK_FEATURE_TYPES;

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onBgImage(typeof reader.result === "string" ? reader.result : null);
    reader.readAsDataURL(file);
    e.target.value = ""; // allow re-picking the same file later
  }

  return (
    <div className={styles.bar} aria-disabled={disabled}>
      <div className={styles.group} role="group" aria-label="Drawing tools">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`${styles.tool} ${tool === t.id ? styles.toolActive : ""}`}
            onClick={() => onTool(t.id)}
            disabled={disabled}
            title={`${t.label} — ${t.hint}`}
            aria-pressed={tool === t.id}
          >
            <Icon name={t.id} />
          </button>
        ))}
      </div>

      <label className={styles.snap} title="Snap coordinates to whole grid units">
        <input
          type="checkbox"
          checked={snap}
          onChange={(e) => onSnap(e.target.checked)}
          disabled={disabled}
        />
        Snap
      </label>

      {snap ? (
        <label
          className={styles.numField}
          title="Snap resolution: 1 = one dot per grid edge, 2 = twice as many dots (half-steps), 3 = thirds, …"
        >
          Res
          <input
            type="number"
            className={styles.num}
            value={snapResolution}
            min={1}
            step={1}
            onChange={(e) =>
              onSnapResolution(Math.max(1, Math.round(Number(e.target.value) || 1)))
            }
            disabled={disabled}
          />
        </label>
      ) : null}

      <label
        className={styles.snap}
        title="Pathing check: rooms/corridors with a door are tinted green, isolated ones red"
      >
        <input
          type="checkbox"
          checked={pathCheck}
          onChange={(e) => onPathCheck(e.target.checked)}
          disabled={disabled}
        />
        Pathing
      </label>

      <label
        className={styles.snap}
        title="In Select mode, click a room/corridor to list the doors connecting it"
      >
        <input
          type="checkbox"
          checked={connectionsMode}
          onChange={(e) => onConnectionsMode(e.target.checked)}
          disabled={disabled}
        />
        Connections
      </label>

      <label
        className={styles.snap}
        title="Draw a per-cell grid inside every room and corridor (adds `cell_grid` to the map block)"
      >
        <input
          type="checkbox"
          checked={cellGrid}
          onChange={(e) => onCellGrid(e.target.checked)}
          disabled={disabled}
        />
        Cell grid
      </label>

      {tool === "door" ? (
        <div className={styles.group} role="group" aria-label="Door options">
          <select
            className={styles.select}
            value={doorType}
            onChange={(e) => onDoorType(e.target.value)}
            disabled={disabled}
            title="Door type"
          >
            {DOOR_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={doorState}
            onChange={(e) => onDoorState(e.target.value)}
            disabled={disabled || doorType === "arch" || doorType === "open"}
            title={
              doorType === "arch" || doorType === "open"
                ? "Openings have no state"
                : "Door state"
            }
          >
            {DOOR_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={doorFacing}
            onChange={(e) => onDoorFacing(e.target.value)}
            disabled={disabled}
            title="Leaf side (auto = inferred by the renderer)"
          >
            {DOOR_FACINGS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <label
            className={styles.snap}
            title="Mark the door trapped (GM only — hidden from the players' fog-of-war view)"
          >
            <input
              type="checkbox"
              checked={doorTrapped}
              onChange={(e) => onDoorTrapped(e.target.checked)}
              disabled={disabled}
            />
            Trapped
          </label>
        </div>
      ) : null}

      {tool === "feature" ? (
        <div className={styles.group} role="group" aria-label="Feature options">
          <select
            className={styles.select}
            value={featureType}
            onChange={(e) => onFeatureType(e.target.value)}
            disabled={disabled}
            title="Feature type"
          >
            {featureGroups.length ? (
              // Grouped by source include file (each sorted); groups sorted.
              featureGroups.map((g) => (
                <optgroup key={g.source} label={g.source}>
                  {g.names.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </optgroup>
              ))
            ) : (
              features.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))
            )}
          </select>
          <label className={styles.numField} title="Rotation (degrees)">
            ⟳
            <input
              type="number"
              className={styles.num}
              value={featureRotate}
              step={15}
              onChange={(e) => onFeatureRotate(Number(e.target.value) || 0)}
              disabled={disabled}
            />
          </label>
          <label className={styles.numField} title="Scale (1 = default)">
            ⤢
            <input
              type="number"
              className={styles.num}
              value={featureScale}
              step={0.25}
              min={0.1}
              onChange={(e) => onFeatureScale(Number(e.target.value) || 1)}
              disabled={disabled}
            />
          </label>
        </div>
      ) : null}

      {tool === "corridor" ? (
        <>
          <label
            className={styles.snap}
            title="Draw corridors with an organic (wavy, hand-drawn) wall style"
          >
            <input
              type="checkbox"
              checked={corridorOrganic}
              onChange={(e) => onCorridorOrganic(e.target.checked)}
              disabled={disabled}
            />
            Organic
          </label>
          <label
            className={styles.snap}
            title="Draw corridors with straight (sharp) corners instead of rounded"
          >
            <input
              type="checkbox"
              checked={corridorStraight}
              onChange={(e) => onCorridorStraight(e.target.checked)}
              disabled={disabled}
            />
            Straight corners
          </label>
        </>
      ) : null}

      {tool === "text" ? (
        <div className={styles.group} role="group" aria-label="Text options">
          <input
            type="text"
            className={styles.select}
            value={textContent}
            placeholder="Text to place"
            onChange={(e) => onTextContent(e.target.value)}
            disabled={disabled}
            title="Text content"
          />
          <label className={styles.numField} title="Font size (1 = a default room label)">
            A
            <input
              type="number"
              className={styles.num}
              value={textSize}
              step={0.25}
              min={0.1}
              onChange={(e) => onTextSize(Number(e.target.value) || 1)}
              disabled={disabled}
            />
          </label>
        </div>
      ) : null}

      {tool === "area" ? (
        <div className={styles.group} role="group" aria-label="Terrain options">
          <select
            className={styles.select}
            value={areaKind}
            onChange={(e) => onAreaKind(e.target.value)}
            disabled={disabled}
            title="Terrain kind"
          >
            {AREA_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <label className={styles.snap} title="Give the area a natural wavy edge (line_style organic)">
            <input
              type="checkbox"
              checked={areaOrganic}
              onChange={(e) => onAreaOrganic(e.target.checked)}
              disabled={disabled}
            />
            Organic
          </label>
        </div>
      ) : null}

      {tool === "line" ? (
        <div className={styles.group} role="group" aria-label="Line feature options">
          <select
            className={styles.select}
            value={lineKind}
            onChange={(e) => onLineKind(e.target.value)}
            disabled={disabled}
            title="Line feature style"
          >
            {LINE_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      <div className={styles.spacer} />

      <button
        type="button"
        className={styles.sortBtn}
        onClick={onSort}
        title="Reorder declarations: rooms (by id), corridors (by id), doors, then features"
      >
        <Icon name="sort" size={15} />
        Sort
      </button>

      <div className={styles.group} role="group" aria-label="Tracing reference">
        <button
          type="button"
          className={styles.refBtn}
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          title="Load a reference image to trace over (stays in your browser; never saved to the map)"
        >
          {bgImage ? "Replace image" : "Reference image"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={onPick}
        />
        {bgImage ? (
          <>
            <input
              className={styles.slider}
              type="range"
              min={0}
              max={100}
              value={Math.round(bgOpacity * 100)}
              onChange={(e) => onBgOpacity(Number(e.target.value) / 100)}
              title="Reference opacity"
              aria-label="Reference opacity"
            />
            <button
              type="button"
              className={styles.refBtn}
              onClick={() => onBgImage(null)}
              title="Remove the reference image"
            >
              Clear
            </button>
          </>
        ) : null}
      </div>

      <span className={styles.hint}>{active.hint}</span>
    </div>
  );
}
