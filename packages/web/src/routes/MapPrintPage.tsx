// Print-friendly view modelled on the AD&D 2nd edition module format:
// map on its own page, then a 3-column room key with bolded heading,
// boxed read-aloud description, plain feature list, and bordered DM
// notes. Drop the page through the browser's Print dialog (Cmd/Ctrl+P)
// to get a clean PDF.
import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { ParsedMap, ParsedRoom } from "../lib/api";
import styles from "./MapPrint.module.css";

interface FeatureEntry {
  name: string;
  description: string;
  dmNotes: string;
}

interface RoomEntry {
  number: string;
  label: string;
  description: string;
  dmNotes: string;
  features: FeatureEntry[];
}

interface AnnotatedEntry {
  label: string;
  description: string;
  dmNotes: string;
}

function indexRooms(parsed: ParsedMap | undefined): Map<string, ParsedRoom> {
  const idx = new Map<string, ParsedRoom>();
  if (!parsed) return idx;
  for (const r of Object.values(parsed.rooms)) idx.set(r.name, r);
  for (const layer of parsed.layers) {
    if (layer.hidden) continue;
    for (const r of layer.rooms) {
      if (!idx.has(r.name)) idx.set(r.name, r);
    }
  }
  return idx;
}

function resolveFeatures(
  room: ParsedRoom | undefined,
  parsed: ParsedMap | undefined,
): FeatureEntry[] {
  if (!room || !parsed) return [];
  return room.features.map((fi) => {
    const def = parsed.feature_defs[fi.ref];
    const name = def?.display_name || def?.name || fi.ref;
    const description = (fi.description ?? def?.description ?? "") || "";
    const dmNotes = fi.dm_notes ?? "";
    return { name, description, dmNotes };
  });
}

function collectFromAttrs(
  doc: Document,
  selector: string,
  idAttr: string,
  label: (el: Element, id: string) => string,
): AnnotatedEntry[] {
  // Multiple SVG nodes can carry the same logical id (a corridor renders
  // as both wall and floor paths). Dedupe by id, keeping whichever node
  // first supplies a description / dm-notes string.
  const seen = new Map<string, AnnotatedEntry>();
  for (const el of Array.from(doc.querySelectorAll(selector))) {
    const id = el.getAttribute(idAttr) ?? "";
    if (!id) continue;
    const description = el.getAttribute("data-description") ?? "";
    const dmNotes = el.getAttribute("data-dm-notes") ?? "";
    if (!description && !dmNotes) continue;
    const existing = seen.get(id);
    if (existing) {
      if (!existing.description && description) existing.description = description;
      if (!existing.dmNotes && dmNotes) existing.dmNotes = dmNotes;
      continue;
    }
    seen.set(id, { label: label(el, id), description, dmNotes });
  }
  return Array.from(seen.values());
}

function collectDoors(doc: Document): AnnotatedEntry[] {
  // Doors have no stable id, so we synthesize one from kind + an ordinal
  // index so the print key can list them in source order.
  const entries: AnnotatedEntry[] = [];
  const counts = new Map<string, number>();
  for (const el of Array.from(doc.querySelectorAll("g.door-instance"))) {
    const description = el.getAttribute("data-description") ?? "";
    const dmNotes = el.getAttribute("data-dm-notes") ?? "";
    if (!description && !dmNotes) continue;
    const kind = el.getAttribute("data-door") ?? "door";
    const next = (counts.get(kind) ?? 0) + 1;
    counts.set(kind, next);
    const baseLabel =
      el.getAttribute("data-label") ||
      `${kind.charAt(0).toUpperCase()}${kind.slice(1)} door`;
    entries.push({
      label: `${baseLabel} #${next}`,
      description,
      dmNotes,
    });
  }
  return entries;
}

export function MapPrintPage() {
  const { mapId = "" } = useParams();

  const { data: map } = useQuery({
    queryKey: ["map", mapId],
    queryFn: () => api.maps.get(mapId),
    enabled: !!mapId,
  });

  const { data: rendered } = useQuery({
    queryKey: ["render", map?.id, map?.source],
    queryFn: () => api.dsl.render(map!.source),
    enabled: !!map,
  });

  const { data: parsed } = useQuery({
    queryKey: ["parse", map?.id, map?.source],
    queryFn: () => api.dsl.parse(map!.source).then((r) => r.map),
    enabled: !!map,
  });

  const svgRef = useRef<HTMLDivElement>(null);

  // Numbering and ordering come from the rendered SVG (single source of
  // truth — matches the labels on the map). Description/features/notes
  // come from the parsed model, joined by room name.
  const { rooms, corridors, doors } = useMemo<{
    rooms: RoomEntry[];
    corridors: AnnotatedEntry[];
    doors: AnnotatedEntry[];
  }>(() => {
    if (!rendered?.svg) return { rooms: [], corridors: [], doors: [] };
    const doc = new DOMParser().parseFromString(
      rendered.svg,
      "image/svg+xml",
    );
    const floors = Array.from(doc.querySelectorAll("path.floor[data-number]"));
    const byName = indexRooms(parsed);
    const roomList: RoomEntry[] = floors.map((el) => {
      const roomName = el.getAttribute("data-room") ?? "";
      const room = byName.get(roomName);
      return {
        number: el.getAttribute("data-number") ?? "",
        label:
          el.getAttribute("data-label") ?? el.getAttribute("data-room") ?? "",
        description: el.getAttribute("data-description") ?? "",
        dmNotes: el.getAttribute("data-dm-notes") ?? "",
        features: resolveFeatures(room, parsed),
      };
    });
    roomList.sort((a, b) => Number(a.number) - Number(b.number));
    const corridorList = collectFromAttrs(
      doc,
      "[data-corridor]",
      "data-corridor",
      (el, id) => el.getAttribute("data-label") || id,
    );
    const doorList = collectDoors(doc);
    return { rooms: roomList, corridors: corridorList, doors: doorList };
  }, [rendered?.svg, parsed]);

  useEffect(() => {
    if (map?.name) document.title = `${map.name} — dungml`;
  }, [map?.name]);

  if (!map) {
    return <div className={styles.loading}>Loading…</div>;
  }

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Link to={`/maps/${mapId}`} className={styles.back}>
          ← Back to editor
        </Link>
        <button
          type="button"
          className={styles.printBtn}
          onClick={() => window.print()}
        >
          Print or save as PDF
        </button>
      </div>

      <header className={styles.header}>
        <h1>{map.name}</h1>
      </header>

      {parsed?.map?.description || parsed?.map?.dm_notes ? (
        <section className={styles.introSection}>
          {parsed.map.description ? (
            <p className={styles.readAloud}>{parsed.map.description}</p>
          ) : null}
          {parsed.map.dm_notes ? (
            <div className={styles.dmBox}>
              <span className={styles.dmTag}>DM</span>
              <span className={styles.dmText}>{parsed.map.dm_notes}</span>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className={styles.mapSection}>
        <div
          ref={svgRef}
          className={styles.mapHolder}
          dangerouslySetInnerHTML={{ __html: rendered?.svg ?? "" }}
        />
      </section>

      <section className={styles.keySection}>
        <h2>Room key</h2>
        {rooms.length === 0 ? (
          <p className={styles.muted}>No labelled rooms.</p>
        ) : (
          <ol className={styles.roomList}>
            {rooms.map((r) => (
              <li key={r.number} className={styles.roomItem}>
                <h3 className={styles.roomHeading}>
                  <span className={styles.roomNumber}>{r.number}.</span>{" "}
                  {r.label}
                </h3>
                {r.description ? (
                  <p className={styles.readAloud}>{r.description}</p>
                ) : null}
                {r.features.length > 0 ? (
                  <p className={styles.features}>
                    <span className={styles.featuresLabel}>Features:</span>{" "}
                    {r.features.map((f, i) => (
                      <span key={i} className={styles.feature}>
                        {i > 0 ? "; " : ""}
                        <span className={styles.featureName}>{f.name}</span>
                        {f.description ? ` — ${f.description}` : ""}
                      </span>
                    ))}
                    .
                  </p>
                ) : null}
                {r.features.some((f) => f.dmNotes) ? (
                  <ul className={styles.featureNotes}>
                    {r.features
                      .filter((f) => f.dmNotes)
                      .map((f, i) => (
                        <li key={i}>
                          <span className={styles.dmTag}>DM</span>
                          <span className={styles.featureName}>{f.name}:</span>{" "}
                          {f.dmNotes}
                        </li>
                      ))}
                  </ul>
                ) : null}
                {r.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>DM</span>
                    <span className={styles.dmText}>{r.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {corridors.length > 0 ? (
        <section className={styles.auxSection}>
          <h2>Corridors</h2>
          <ul className={styles.auxList}>
            {corridors.map((c, i) => (
              <li key={`c-${i}`} className={styles.auxItem}>
                <span className={styles.auxLabel}>{c.label}</span>
                {c.description ? (
                  <span className={styles.auxBody}>{c.description}</span>
                ) : null}
                {c.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>DM</span>
                    <span className={styles.dmText}>{c.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {doors.length > 0 ? (
        <section className={styles.auxSection}>
          <h2>Doors</h2>
          <ul className={styles.auxList}>
            {doors.map((d, i) => (
              <li key={`d-${i}`} className={styles.auxItem}>
                <span className={styles.auxLabel}>{d.label}</span>
                {d.description ? (
                  <span className={styles.auxBody}>{d.description}</span>
                ) : null}
                {d.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>DM</span>
                    <span className={styles.dmText}>{d.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
