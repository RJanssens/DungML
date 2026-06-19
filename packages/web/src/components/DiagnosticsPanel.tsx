import type { Diagnostic } from "../lib/types";
import styles from "./DiagnosticsPanel.module.css";

export function DiagnosticsPanel({
  diagnostics,
  onJump,
}: {
  diagnostics: Diagnostic[];
  onJump?: (d: Diagnostic) => void;
}) {
  const errs = diagnostics.filter((d) => d.severity === "error").length;
  const warns = diagnostics.filter((d) => d.severity === "warning").length;
  const ok = errs === 0 && warns === 0;
  return (
    <div className={styles.panel}>
      <div className={`${styles.status} ${ok ? styles.statusOk : ""}`}>
        {ok ? (
          <span>No issues.</span>
        ) : (
          <span>
            {errs > 0 ? (
              <span className={styles.errCount}>
                {errs} error{errs === 1 ? "" : "s"}
              </span>
            ) : null}
            {errs > 0 && warns > 0 ? " · " : ""}
            {warns > 0 ? (
              <span className={styles.warnCount}>
                {warns} warning{warns === 1 ? "" : "s"}
              </span>
            ) : null}
          </span>
        )}
      </div>
      {diagnostics.length > 0 ? (
        <ul className={styles.list}>
          {diagnostics.map((d, i) => (
            <li
              key={i}
              className={`${styles.item} ${
                d.severity === "error" ? styles.itemErr : styles.itemWarn
              }`}
              onClick={() => onJump?.(d)}
            >
              <span className={styles.line}>
                {d.line > 0 ? `${d.line}:${d.column}` : "—"}
              </span>
              <span className={styles.message}>{d.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
