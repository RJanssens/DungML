// Who can work on a project besides its owner. The backend keeps ownership
// in `projects.user_id` and co-access in `project_members`, so this panel
// shows the owner as a line of text and the members as removable rows.
//
// Adding and removing are owner-only server-side; the controls are hidden
// for a member rather than shown and then rejected.
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { Button, Card, Input } from "./Primitives";
import styles from "./ProjectMembers.module.css";

export function ProjectMembers({
  projectId,
  isOwner,
  owner,
}: {
  projectId: string;
  isOwner: boolean;
  owner: string;
}) {
  const qc = useQueryClient();
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: members = [] } = useQuery({
    queryKey: ["project-members", projectId],
    queryFn: () => api.projects.members.list(projectId),
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["project-members", projectId] });

  const add = useMutation({
    mutationFn: (who: string) => api.projects.members.add(projectId, who),
    onSuccess: () => {
      setIdentifier("");
      setError(null);
      invalidate();
    },
    onError: (e: unknown) =>
      setError(e instanceof Error ? e.message : "could not share the project"),
  });

  const remove = useMutation({
    mutationFn: (userId: string) =>
      api.projects.members.remove(projectId, userId),
    onSuccess: invalidate,
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const who = identifier.trim();
    if (who) add.mutate(who);
  }

  return (
    <Card className={styles.panel}>
      <h3 className={styles.heading}>People</h3>
      <p className={styles.owner}>Owner: {owner || "unknown"}</p>
      {members.length === 0 ? (
        <p className={styles.empty}>Not shared with anyone yet.</p>
      ) : (
        <ul className={styles.list}>
          {members.map((m) => (
            <li key={m.user_id} className={styles.row}>
              <span className={styles.who}>
                {m.email || m.subject}
                {/* A subject beginning with "@" is a service principal, not a
                    person — it's here because a campaign is linked to this
                    project, and it's what drives the fog. */}
                {m.subject.startsWith("@") ? (
                  <span className={styles.tag}> — campaign service</span>
                ) : null}
              </span>
              {isOwner ? (
                <Button
                  variant="ghost"
                  onClick={() => remove.mutate(m.user_id)}
                  title="Revoke access"
                >
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {isOwner ? (
        <form className={styles.form} onSubmit={onSubmit}>
          <Input
            placeholder="Email or subject"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            maxLength={255}
          />
          <Button type="submit" disabled={add.isPending}>
            Share
          </Button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}
    </Card>
  );
}
