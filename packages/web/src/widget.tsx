// Embeddable build entry point. Produces a single self-contained script
// (dungml-play.js) that mounts the fog-of-war play view into any host page —
// no React, router, or build tooling required on the host side.
//
//   <div id="map" style="height: 600px"></div>
//   <script src="https://dungml.example.com/dungml-play.js"></script>
//   <script>
//     DungmlPlay.mount(document.getElementById("map"), {
//       baseUrl: "https://dungml.example.com",
//       mapId: "the-map-uuid",
//       getToken: () => myApp.currentDungmlToken,  // or token: "abc..."
//     });
//   </script>
//
// The host app owns identity and authorization; it supplies a dungml bearer
// token and a mapId, and dungml remains the source of truth for session and
// exploration state.
import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { configureApi } from "./lib/api";
import { PlayConsole } from "./components/PlayConsole";

export interface MountOptions {
  /** The map to play. Required. */
  mapId: string;
  /** Origin of the dungml backend, e.g. "https://dungml.example.com".
   * Defaults to same-origin. */
  baseUrl?: string;
  /** Static bearer token for the dungml backend. */
  token?: string;
  /** Token provider, called on every request (use this for tokens that
   * refresh). Takes precedence over `token`. */
  getToken?: () => string | null;
  /** Pin the view to a specific play session (auto-opened, no picker). The
   * host app owns which session a party plays. */
  sessionId?: string;
  /** Read-only player view: show only the discovered map + party location,
   * polling for updates. Hides all GM/session controls (move, reveal, GM
   * view, session list) — those belong in the dungml app. Default false. */
  playerView?: boolean;
}

const roots = new WeakMap<Element, Root>();

/** Mount the play view into `el`. Re-mounting on the same element first
 * unmounts the previous instance. */
export function mount(el: Element, opts: MountOptions): void {
  if (!el) throw new Error("DungmlPlay.mount: target element is required");
  if (!opts?.mapId) throw new Error("DungmlPlay.mount: opts.mapId is required");

  configureApi({
    baseUrl: opts.baseUrl ?? "",
    getToken: opts.getToken ?? (() => opts.token ?? null),
  });

  unmount(el);
  const root = createRoot(el);
  roots.set(el, root);
  root.render(
    <StrictMode>
      <PlayConsole
        mapId={opts.mapId}
        sessionId={opts.sessionId}
        playerView={opts.playerView}
      />
    </StrictMode>,
  );
}

/** Tear down a previously-mounted instance. Safe to call on an empty element. */
export function unmount(el: Element): void {
  const root = roots.get(el);
  if (root) {
    root.unmount();
    roots.delete(el);
  }
}
