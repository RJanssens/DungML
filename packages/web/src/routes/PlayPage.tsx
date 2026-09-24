// SPA route for the fog-of-war play view: wraps the reusable PlayConsole in
// the app chrome (header + back-to-editor link). All the play logic lives in
// PlayConsole, which is also what the embeddable widget mounts.
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AppHeader, PageShell } from "../components/Layout";
import { PlayConsole } from "../components/PlayConsole";

export function PlayPage() {
  const { mapId = "" } = useParams();
  // `?session=` pins the view to one session, skipping the picker — how the
  // project page links to the session an external campaign is driving.
  const [params] = useSearchParams();
  const sessionId = params.get("session") ?? undefined;
  return (
    <PageShell>
      <AppHeader right={<Link to={`/maps/${mapId}`}>← Back to editor</Link>} />
      <div style={{ height: "calc(100vh - 64px)" }}>
        <PlayConsole mapId={mapId} sessionId={sessionId} />
      </div>
    </PageShell>
  );
}
