// Every play session in a project, with how far each has got.
//
// Progress has always been in the map's play view ("Explored 7 / 18 areas"),
// but only for the map you already had open — a project of twenty maps meant
// opening twenty of them to find the session you were after. This lists them
// all, most recently active first, and links straight into each.
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import type { ProjectSession } from "../lib/types";
import { Button, Card } from "./Primitives";
import styles from "./ProjectSessions.module.css";

/** Deleting a session throws away the fog it recorded, and for a session an
 * external campaign drives, that campaign starts its next scene with a blank
 * map — so say whose exploration is about to go. */
function confirmText(s: ProjectSession): string {
  const progress =
    s.total_nodes > 0
      ? `${s.discovered_nodes} of ${s.total_nodes} areas`
      : `${s.discovered_nodes} areas`;
  const driven = s.external_id
    ? `\n\nThis is the live session for "${s.external_id}" — that campaign will start again from an unexplored map.`
    : "";
  return `Delete "${s.name}" on ${s.map_name}?\n\nIts exploration (${progress}) and party position are lost. The map itself is untouched.${driven}`;
}

export function ProjectSessions({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const { data: sessions = [] } = useQuery({
    queryKey: ["project-sessions", projectId],
    queryFn: () => api.projects.sessions(projectId),
    refetchInterval: 30_000,
  });

  const remove = useMutation({
    mutationFn: (sessionId: string) => api.sessions.remove(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-sessions", projectId] });
      // A deleted session can be the one a campaign row points at.
      qc.invalidateQueries({ queryKey: ["project-campaigns", projectId] });
    },
  });

  if (sessions.length === 0) return null;

  return (
    <Card className={styles.panel}>
      <h3 className={styles.heading}>Play sessions</h3>
      <ul className={styles.list}>
        {sessions.map((s) => {
          const pct =
            s.total_nodes > 0
              ? Math.round((s.discovered_nodes / s.total_nodes) * 100)
              : 0;
          return (
            <li
              key={s.session_id}
              className={styles.row}
              data-driven={s.external_id ? "true" : "false"}
            >
              <Link
                to={`/maps/${s.map_id}/play?session=${s.session_id}`}
                className={styles.name}
              >
                {s.name}
              </Link>
              <span className={styles.where}>
                {s.map_name}
                {s.party_location ? ` — party at ${s.party_location}` : ""}
                {s.external_id ? (
                  <span className={styles.live}> · driven by {s.external_id}</span>
                ) : null}
              </span>
              <span
                className={styles.bar}
                title={`${pct}% explored`}
                aria-hidden="true"
              >
                <span className={styles.barFill} style={{ width: `${pct}%` }} />
              </span>
              <span className={styles.progress}>
                {s.total_nodes > 0
                  ? `${s.discovered_nodes} / ${s.total_nodes} areas`
                  : `${s.discovered_nodes} areas`}
              </span>
              <Button
                variant="danger"
                title="Delete session"
                aria-label={`Delete session ${s.name}`}
                disabled={remove.isPending}
                onClick={() => {
                  if (confirm(confirmText(s))) remove.mutate(s.session_id);
                }}
              >
                ✕
              </Button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
