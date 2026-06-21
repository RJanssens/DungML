// Fog-of-war play console: track the party's location and reveal the map as
// they explore. The heavy lifting (discovery overlay, fog rendering) lives in
// the backend /api/sessions/* routes; this component is the GM/player console.
//
// It is deliberately router-free and chrome-free: it takes a `mapId` prop and
// fills its parent container. The SPA wraps it in PlayPage (header + back
// link); the embeddable widget mounts it directly into a host element.
import { useCallback, useEffect, useState } from "react";
import * as api from "../lib/api";
import type { SessionState } from "../lib/api";
import { Button, Input } from "./Primitives";
import { SvgPreview } from "./SvgPreview";

interface NodeOpt {
  id: string;
  name: string;
  kind: string;
}

export function PlayConsole({
  mapId,
  sessionId,
  playerView = false,
}: {
  mapId: string;
  /** Auto-open this session and skip the picker (host-pinned). */
  sessionId?: string;
  /** Read-only player view: discovered map + party location only, no GM
   * controls; polls so it tracks moves the GM makes elsewhere. */
  playerView?: boolean;
}) {
  const [mapName, setMapName] = useState("");
  const [nodes, setNodes] = useState<NodeOpt[]>([]);
  const [list, setList] = useState<SessionState[]>([]);
  const [session, setSession] = useState<SessionState | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [view, setView] = useState<"discovered" | "full">("discovered");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState("Session 1");
  const [startLoc, setStartLoc] = useState("");

  const refreshList = useCallback(() => {
    if (mapId) api.sessions.list(mapId).then(setList).catch(() => {});
  }, [mapId]);

  // Map name + node list (for start-location / reveal pickers) + sessions.
  useEffect(() => {
    if (!mapId) return;
    api.maps
      .get(mapId)
      .then((m) => {
        setMapName(m.name);
        api.dsl
          .connectivity(m.source)
          .then((c) => {
            const ns = c.nodes.map((n) => ({ id: n.id, name: n.name, kind: n.kind }));
            setNodes(ns);
            setStartLoc((s) => s || (ns[0]?.id ?? ""));
          })
          .catch(() => {});
      })
      .catch((e) => setErr(String(e?.message ?? e)));
    refreshList();
  }, [mapId, refreshList]);

  const loadRender = useCallback((id: string, v: "discovered" | "full") => {
    setLoading(true);
    api.sessions
      .render(id, v)
      .then((r) => {
        setSvg(r.svg);
        setErr(null);
      })
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  const openSession = useCallback(
    (s: SessionState) => {
      setSession(s);
      loadRender(s.id, view);
    },
    [view, loadRender],
  );

  // Re-render when the GM/player view toggle changes.
  useEffect(() => {
    if (session) loadRender(session.id, view);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // Host-pinned session: auto-open it and skip the picker entirely.
  useEffect(() => {
    if (!sessionId) return;
    api.sessions
      .get(sessionId)
      .then((s) => {
        setSession(s);
        loadRender(s.id, playerView ? "discovered" : view);
      })
      .catch((e) => setErr(String(e?.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Player view: poll so the map tracks moves/reveals the GM makes in the
  // dungml app. Quiet refresh — no loading flicker on each tick.
  useEffect(() => {
    if (!playerView || !session) return;
    const id = session.id;
    const tick = () => {
      api.sessions.get(id).then(setSession).catch(() => {});
      api.sessions
        .render(id, "discovered")
        .then((r) => setSvg(r.svg))
        .catch(() => {});
    };
    const handle = setInterval(tick, 6000);
    return () => clearInterval(handle);
  }, [playerView, session?.id]);

  const create = async () => {
    try {
      const s = await api.sessions.create(
        mapId,
        newName || "Session",
        startLoc || undefined,
      );
      refreshList();
      openSession(s);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  };

  const move = async (to: string) => {
    if (!session) return;
    const s = await api.sessions.move(session.id, to);
    setSession(s);
    loadRender(s.id, view);
  };

  const reveal = async (node: string) => {
    if (!session || !node) return;
    const s = await api.sessions.reveal(session.id, node);
    setSession(s);
    loadRender(s.id, view);
  };

  const del = async (id: string) => {
    await api.sessions.remove(id);
    if (session?.id === id) {
      setSession(null);
      setSvg(null);
    }
    refreshList();
  };

  // Read-only player view: just the discovered map + party location. No GM
  // chrome — moving/revealing/GM-view live in the dungml app.
  if (playerView) {
    const partyName = session?.party_location
      ? session.party_location.split(".").slice(1).join(".") ||
        session.party_location
      : null;
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          boxSizing: "border-box",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "0.75rem",
            padding: "0.5rem 0.75rem",
            flexWrap: "wrap",
          }}
        >
          {mapName && <strong>{mapName}</strong>}
          {partyName && (
            <span>
              Party: <code>{partyName}</code>
            </span>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
          <SvgPreview
            svg={svg}
            loading={loading}
            error={err}
            notice={session ? null : "Waiting for the GM to start a session…"}
            focusTarget={session?.party_location ?? null}
          />
        </div>
      </div>
    );
  }

  const panel: React.CSSProperties = {
    width: 300,
    flexShrink: 0,
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "0.75rem",
    padding: "0.5rem 0.25rem",
  };

  return (
    <div
      style={{
        display: "flex",
        gap: "1rem",
        padding: "1rem",
        height: "100%",
        boxSizing: "border-box",
      }}
    >
      <aside style={panel}>
        <h2 style={{ margin: 0 }}>Play — {mapName}</h2>

        {!session ? (
          <>
            <section style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <h3 style={{ margin: "0.5rem 0 0" }}>New session</h3>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Session name"
              />
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                Start location
                <select value={startLoc} onChange={(e) => setStartLoc(e.target.value)}>
                  <option value="">(none — set later)</option>
                  {nodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name} ({n.kind})
                    </option>
                  ))}
                </select>
              </label>
              <Button onClick={create}>Start session</Button>
            </section>

            <section>
              <h3 style={{ margin: "0.5rem 0" }}>Saved sessions</h3>
              {list.length === 0 ? (
                <p style={{ color: "#777" }}>None yet.</p>
              ) : (
                list.map((s) => (
                  <div key={s.id} style={{ display: "flex", gap: 6, marginBottom: 4 }}>
                    <Button variant="secondary" onClick={() => openSession(s)} style={{ flex: 1 }}>
                      {s.name}
                      <span style={{ color: "#888", marginLeft: 6 }}>
                        ({s.discovered_nodes.length} explored)
                      </span>
                    </Button>
                    <Button variant="danger" onClick={() => del(s.id)} title="Delete session">
                      ✕
                    </Button>
                  </div>
                ))
              )}
            </section>
          </>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <strong>{session.name}</strong>
              <Button
                variant="ghost"
                onClick={() => {
                  setSession(null);
                  setSvg(null);
                  refreshList();
                }}
              >
                change
              </Button>
            </div>

            <div>
              Party at: <code>{session.party_location ?? "—"}</code>
            </div>
            <div style={{ color: "#777" }}>
              Explored {session.discovered_nodes.length} / {nodes.length} areas
            </div>

            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={view === "full"}
                onChange={(e) => setView(e.target.checked ? "full" : "discovered")}
              />
              GM view (reveal whole map)
            </label>

            <section>
              <h3 style={{ margin: "0.5rem 0" }}>Move party</h3>
              {session.exits.length === 0 ? (
                <p style={{ color: "#777" }}>
                  No known exits{session.party_location ? "" : " — set a start location"}.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {session.exits.map((ex) => (
                    <Button
                      key={ex.door + ex.to}
                      variant="secondary"
                      onClick={() => move(ex.to)}
                      disabled={ex.blocked}
                      title={`${ex.type} door (${ex.state})${
                        ex.blocked ? " — blocked" : ""
                      }${ex.discovered ? "" : " — unexplored"}`}
                    >
                      → {ex.name}
                      {ex.discovered ? "" : " (?)"}
                      {ex.blocked ? " 🔒" : ""}
                    </Button>
                  ))}
                </div>
              )}
            </section>

            <section>
              <h3 style={{ margin: "0.5rem 0" }}>Reveal (GM)</h3>
              <select
                value=""
                onChange={(e) => reveal(e.target.value)}
                title="Reveal a node the party hasn't reached (e.g. behind a secret door)"
              >
                <option value="">Reveal a hidden area…</option>
                {nodes
                  .filter((n) => !session.discovered_nodes.includes(n.id))
                  .map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name} ({n.kind})
                    </option>
                  ))}
              </select>
            </section>
          </>
        )}
      </aside>

      <main style={{ flex: 1, minWidth: 0 }}>
        <SvgPreview
          svg={svg}
          loading={loading}
          error={err}
          notice={session ? null : "Pick or start a session to begin."}
          focusTarget={session?.party_location ?? null}
        />
      </main>
    </div>
  );
}
