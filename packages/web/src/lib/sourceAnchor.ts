// The renderer anchors every drawn entity to its source range with
// `data-src="L:C-L:C"` (1-based, as the parser reports spans). These helpers
// pick which entity an editor cursor is on, so the map can highlight it.

export interface CursorPos {
  line: number;
  column: number;
}

type Range = [number, number, number, number];

const SRC_RE = /^(\d+):(\d+)-(\d+):(\d+)$/;

export function parseSrc(value: string): Range | null {
  const m = SRC_RE.exec(value);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])] : null;
}

function before(l1: number, c1: number, l2: number, c2: number): boolean {
  return l1 < l2 || (l1 === l2 && c1 <= c2);
}

/** The narrowest anchor containing `pos` (ends inclusive), or null. The
 *  narrowest wins so a feature is picked over the room around it. */
export function innermostAnchor(
  values: Iterable<string>,
  pos: CursorPos,
): string | null {
  let best: { value: string; lines: number; cols: number } | null = null;
  for (const value of values) {
    const r = parseSrc(value);
    if (!r) continue;
    const [l1, c1, l2, c2] = r;
    if (!before(l1, c1, pos.line, pos.column) || !before(pos.line, pos.column, l2, c2)) {
      continue;
    }
    const lines = l2 - l1;
    const cols = lines === 0 ? c2 - c1 : Number.MAX_SAFE_INTEGER;
    if (!best || lines < best.lines || (lines === best.lines && cols < best.cols)) {
      best = { value, lines, cols };
    }
  }
  return best ? best.value : null;
}
