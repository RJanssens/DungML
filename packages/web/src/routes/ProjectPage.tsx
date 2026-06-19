import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { MapKind, MapSummary } from "../lib/types";
import { Button, Card, EmptyState, Input } from "../components/Primitives";
import { AppHeader, PageBody, PageShell } from "../components/Layout";
import { relativeTime } from "./ProjectsPage";
import styles from "./Lists.module.css";

const STARTER_DMAP = `# Built-in feature library (pillar, stairs, chest, …). Remove this line
# if you don't use built-in features, or swap it for your own template.
include "core.dmap"

map "Untitled" {
  grid {
    cell    32 px
    units   feet 5
    bounds  30 x 20
    origin  top-left
  }
  renderer "classic-bw"
}

room "main" {
  rect 5,5 10 x 8
  label "Main"
  feature stairs-up at 9,9
}
`;

// Starter content for a library file — no top-level map block so the
// backend tags it as kind="library", just a placeholder feature_def to
// demo the file's purpose.
const STARTER_LIBRARY = `# Library file — feature_defs and other shared declarations.
# Include from a map with:  include "this-file-name.dmap"
# (no top-level map { } block)

feature_def "my_widget" {
  name "Widget"
  shape rect 1 x 1
  background "#999999"
  outline { color "#333333" width 0.06 stroke solid }
}
`;

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [creatingKind, setCreatingKind] = useState<MapKind | null>(null);
  const [name, setName] = useState("");
  const [showCatalog, setShowCatalog] = useState(false);

  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId,
  });
  const { data: maps = [], isLoading } = useQuery({
    queryKey: ["maps", projectId],
    queryFn: () => api.maps.list(projectId),
    enabled: !!projectId,
  });

  const { renderableMaps, libraryFiles } = useMemo(() => {
    const renderable: MapSummary[] = [];
    const library: MapSummary[] = [];
    for (const m of maps) {
      (m.kind === "library" ? library : renderable).push(m);
    }
    return { renderableMaps: renderable, libraryFiles: library };
  }, [maps]);

  const create = useMutation({
    mutationFn: ({ n, kind }: { n: string; kind: MapKind }) =>
      api.maps.create(
        projectId,
        n,
        kind === "library" ? STARTER_LIBRARY : STARTER_DMAP,
      ),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["maps", projectId] });
      navigate(`/maps/${m.id}`);
    },
  });

  // Bundled include libraries (forest, outdoor, …) the user can pull into
  // the project as editable copies. Fetched only when the picker is open.
  const { data: catalog = [] } = useQuery({
    queryKey: ["library-catalog", projectId],
    queryFn: () => api.projects.libraryCatalog(projectId),
    enabled: !!projectId && showCatalog,
  });
  const importLib = useMutation({
    mutationFn: (n: string) => api.projects.importLibrary(projectId, n),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["maps", projectId] });
      qc.invalidateQueries({ queryKey: ["library-catalog", projectId] });
    },
  });

  const [exporting, setExporting] = useState(false);
  async function onExport() {
    setExporting(true);
    try {
      const blob = await api.projects.export(projectId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const base = (project?.name ?? "project").replace(/[^A-Za-z0-9._-]+/g, "-");
      a.download = `${base || "project"}.dmapproj`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!creatingKind) return;
    if (name.trim()) create.mutate({ n: name.trim(), kind: creatingKind });
  }

  return (
    <PageShell>
      <AppHeader
        right={
          <>
            <Link to="/" className={styles.crumb}>
              Projects
            </Link>
            <span className={styles.crumbSep}>/</span>
            <h1 className={styles.headerTitle}>{project?.name ?? "…"}</h1>
          </>
        }
      />
      <PageBody>
        <div className={styles.container}>
          <div className={styles.toolbar}>
            <div className={styles.toolbarSpacer} />
            <Button
              variant="secondary"
              disabled={exporting || maps.length === 0}
              onClick={onExport}
              title="Download this project (all maps) as a .dmapproj archive"
            >
              {exporting ? "Exporting…" : "Export project"}
            </Button>
            <Button
              variant={showCatalog ? "ghost" : undefined}
              onClick={() => setShowCatalog((v) => !v)}
            >
              {showCatalog ? "Cancel" : "Add library"}
            </Button>
            <Button
              variant={creatingKind === "library" ? "ghost" : undefined}
              onClick={() =>
                setCreatingKind((k) => (k === "library" ? null : "library"))
              }
            >
              {creatingKind === "library" ? "Cancel" : "New library file"}
            </Button>
            <Button
              onClick={() =>
                setCreatingKind((k) => (k === "map" ? null : "map"))
              }
            >
              {creatingKind === "map" ? "Cancel" : "New map"}
            </Button>
          </div>

          {creatingKind ? (
            <Card className={styles.createCard}>
              <form onSubmit={onCreate} className={styles.createForm}>
                <Input
                  autoFocus
                  placeholder={
                    creatingKind === "library"
                      ? "Library filename (e.g. wilderness-trees)"
                      : "Map name (e.g. Crypt of St. Vellis)"
                  }
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={200}
                />
                <Button type="submit" disabled={create.isPending}>
                  Create
                </Button>
              </form>
            </Card>
          ) : null}

          {showCatalog ? (
            <Card className={styles.createCard}>
              <p className={styles.muted}>
                Copy a bundled feature library into this project. It becomes an
                editable library file here, and <code>include</code> picks up
                your edited copy.
              </p>
              <ul className={styles.list}>
                {catalog.map((lib) => (
                  <li key={lib.name} className={styles.listItem}>
                    <span className={styles.itemName}>{lib.name}</span>
                    <div className={styles.itemActions}>
                      <Button
                        variant={lib.added ? "ghost" : undefined}
                        disabled={lib.added || importLib.isPending}
                        onClick={() => importLib.mutate(lib.name)}
                      >
                        {lib.added ? "Added" : "Add"}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {isLoading ? (
            <div className={styles.muted}>Loading…</div>
          ) : maps.length === 0 ? (
            <EmptyState
              title="No maps in this project"
              hint="A map is a single .dmap file. Create one to start editing."
              action={
                <Button onClick={() => setCreatingKind("map")}>New map</Button>
              }
            />
          ) : (
            <>
              <section className={styles.section}>
                <h2 className={styles.sectionTitle}>Maps</h2>
                {renderableMaps.length === 0 ? (
                  <p className={styles.muted}>
                    No renderable maps yet.
                  </p>
                ) : (
                  <ul className={styles.list}>
                    {renderableMaps.map((m) => (
                      <MapRow key={m.id} map={m} projectId={projectId} />
                    ))}
                  </ul>
                )}
              </section>

              {libraryFiles.length > 0 ? (
                <section className={styles.section}>
                  <h2 className={styles.sectionTitle}>
                    Library files
                    <span className={styles.sectionHint}>
                      &nbsp;— include-only, no `map &#123; … &#125;` block
                    </span>
                  </h2>
                  <ul className={styles.list}>
                    {libraryFiles.map((m) => (
                      <MapRow key={m.id} map={m} projectId={projectId} />
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          )}
        </div>
      </PageBody>
    </PageShell>
  );
}

function MapRow({ map, projectId }: { map: MapSummary; projectId: string }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(map.name);
  const rename = useMutation({
    mutationFn: (n: string) => api.maps.update(map.id, { name: n }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["maps", projectId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.maps.remove(map.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["maps", projectId] }),
  });

  return (
    <li className={styles.listItem}>
      {editing ? (
        <form
          className={styles.renameForm}
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && name !== map.name) rename.mutate(name.trim());
            else setEditing(false);
          }}
        >
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              setEditing(false);
              setName(map.name);
            }}
            required
          />
        </form>
      ) : (
        <Link to={`/maps/${map.id}`} className={styles.itemLink}>
          <span className={styles.itemName}>{map.name}</span>
          <span className={styles.itemMeta}>
            Updated {relativeTime(map.updated_at)}
          </span>
        </Link>
      )}
      <div className={styles.itemActions}>
        <Button variant="ghost" onClick={() => setEditing((v) => !v)}>
          Rename
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            const label = map.kind === "library" ? "library file" : "map";
            if (confirm(`Delete ${label} "${map.name}"?`)) remove.mutate();
          }}
        >
          Delete
        </Button>
      </div>
    </li>
  );
}
