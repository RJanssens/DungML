// External campaigns — a ttrpg2 game — playing on this project's maps.
//
// ttrpg2 drives a play session over the /campaigns contract: it moves the
// party and reveals rooms as the party explores, and reports which map it is
// on. None of that was visible from here, so the GM had no way to tell which
// of a map's sessions was the live one. This panel names the campaign, the
// map it's on and where the party stands, and links straight into that
// session's play view.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as api from "../lib/api";
import { Card } from "./Primitives";
import styles from "./LiveCampaigns.module.css";

export function LiveCampaigns({ projectId }: { projectId: string }) {
  const { data: campaigns = [] } = useQuery({
    queryKey: ["project-campaigns", projectId],
    queryFn: () => api.projects.campaigns(projectId),
    // The party moves while the GM has this open.
    refetchInterval: 15_000,
  });

  if (campaigns.length === 0) return null;

  return (
    <Card className={styles.panel}>
      <h3 className={styles.heading}>Live campaigns</h3>
      <ul className={styles.list}>
        {campaigns.map((c) => (
          <li key={c.external_id} className={styles.row}>
            <span className={styles.slug}>{c.external_id}</span>
            {c.active_map_id && c.session_id ? (
              <>
                <span className={styles.detail}>
                  {c.active_map_name} — party at{" "}
                  {c.party_location ?? "an unrecorded spot"},{" "}
                  {c.total_nodes > 0
                    ? `${c.discovered_nodes} / ${c.total_nodes} areas uncovered`
                    : `${c.discovered_nodes} areas uncovered`}
                </span>
                <Link to={`/maps/${c.active_map_id}/play?session=${c.session_id}`}>
                  Open
                </Link>
              </>
            ) : (
              <span className={styles.idle}>no map in play yet</span>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
