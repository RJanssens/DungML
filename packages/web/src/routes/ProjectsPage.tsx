import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { Project } from "../lib/types";
import { Button, Card, EmptyState, Input } from "../components/Primitives";
import { AppHeader, PageBody, PageShell } from "../components/Layout";
import styles from "./Lists.module.css";

export function ProjectsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects.list,
  });

  const create = useMutation({
    mutationFn: (n: string) => api.projects.create(n),
    onSuccess: () => {
      setCreating(false);
      setName("");
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const importSamples = useMutation({
    mutationFn: api.projects.importSamples,
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    },
  });

  function onCreate(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  }

  return (
    <PageShell>
      <AppHeader
        right={
          <h1 className={styles.headerTitle}>Projects</h1>
        }
      />
      <PageBody>
        <div className={styles.container}>
          <div className={styles.toolbar}>
            <div className={styles.toolbarSpacer} />
            <Button
              variant="secondary"
              disabled={importSamples.isPending}
              onClick={() => importSamples.mutate()}
              title="Create a project with the bundled sample maps"
            >
              {importSamples.isPending ? "Importing…" : "Import samples"}
            </Button>
            <Button onClick={() => setCreating((v) => !v)}>
              {creating ? "Cancel" : "New project"}
            </Button>
          </div>
          {creating ? (
            <Card className={styles.createCard}>
              <form onSubmit={onCreate} className={styles.createForm}>
                <Input
                  autoFocus
                  placeholder="Project name"
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

          {isLoading ? (
            <div className={styles.muted}>Loading…</div>
          ) : projects.length === 0 ? (
            <EmptyState
              title="No projects yet"
              hint="Projects group related maps. Start with the bundled samples or create one from scratch."
              action={
                <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                  <Button
                    variant="secondary"
                    disabled={importSamples.isPending}
                    onClick={() => importSamples.mutate()}
                  >
                    {importSamples.isPending ? "Importing…" : "Import samples"}
                  </Button>
                  <Button onClick={() => setCreating(true)}>
                    New project
                  </Button>
                </div>
              }
            />
          ) : (
            <ul className={styles.list}>
              {projects.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </ul>
          )}
        </div>
      </PageBody>
    </PageShell>
  );
}

function ProjectRow({ project }: { project: Project }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const rename = useMutation({
    mutationFn: (n: string) => api.projects.rename(project.id, n),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.projects.remove(project.id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  return (
    <li className={styles.listItem}>
      {editing ? (
        <form
          className={styles.renameForm}
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && name !== project.name) rename.mutate(name.trim());
            else setEditing(false);
          }}
        >
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              setEditing(false);
              setName(project.name);
            }}
            required
          />
        </form>
      ) : (
        <Link to={`/projects/${project.id}`} className={styles.itemLink}>
          <span className={styles.itemName}>{project.name}</span>
          <span className={styles.itemMeta}>
            Updated {relativeTime(project.updated_at)}
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
            if (confirm(`Delete "${project.name}" and all its maps?`)) {
              remove.mutate();
            }
          }}
        >
          Delete
        </Button>
      </div>
    </li>
  );
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, (now - then) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
