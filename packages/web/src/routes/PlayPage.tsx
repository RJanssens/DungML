// SPA route for the fog-of-war play view: wraps the reusable PlayConsole in
// the app chrome (header + back-to-editor link). All the play logic lives in
// PlayConsole, which is also what the embeddable widget mounts.
import { Link, useParams } from "react-router-dom";
import { AppHeader, PageShell } from "../components/Layout";
import { PlayConsole } from "../components/PlayConsole";

export function PlayPage() {
  const { mapId = "" } = useParams();
  return (
    <PageShell>
      <AppHeader right={<Link to={`/maps/${mapId}`}>← Back to editor</Link>} />
      <div style={{ height: "calc(100vh - 64px)" }}>
        <PlayConsole mapId={mapId} />
      </div>
    </PageShell>
  );
}
