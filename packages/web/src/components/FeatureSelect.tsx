// A searchable combobox for picking a feature type. Behaves like a <select>
// (shows the current value, click to open) but the text field filters the
// options inline as you type, with the source-file grouping preserved.
// Keyboard: ↑/↓ move, Enter selects the highlighted option, Esc closes.
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import styles from "./FeatureSelect.module.css";

export interface FeatureGroup {
  source: string;
  names: string[];
}

export function FeatureSelect({
  value,
  onChange,
  groups,
  fallback,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  groups: FeatureGroup[];
  fallback: string[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const q = query.trim().toLowerCase();
  // Grouped options matching the query (groups with no match drop out). Falls
  // back to a single anonymous group when the backend hasn't reported sources.
  const display = useMemo<FeatureGroup[]>(() => {
    const src: FeatureGroup[] = groups.length
      ? groups
      : [{ source: "", names: fallback }];
    return src
      .map((g) => ({
        source: g.source,
        names: g.names.filter((n) => !q || n.toLowerCase().includes(q)),
      }))
      .filter((g) => g.names.length);
  }, [groups, fallback, q]);
  const flat = useMemo(() => display.flatMap((g) => g.names), [display]);

  function close() {
    setOpen(false);
    setQuery("");
  }

  function openList() {
    if (disabled) return;
    setQuery("");
    setOpen(true);
  }

  function choose(name: string) {
    onChange(name);
    close();
    inputRef.current?.blur();
  }

  // Close when clicking outside.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close();
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // On open, highlight the current selection; while typing, keep the highlight
  // in range of the (shrinking) list.
  useEffect(() => {
    if (!open) return;
    const i = flat.indexOf(value);
    setActive(i >= 0 ? i : 0);
    // Only when opening — typing is handled by the clamp effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  useEffect(() => {
    setActive((a) => Math.min(Math.max(0, a), Math.max(0, flat.length - 1)));
  }, [flat.length]);

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (disabled) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) openList();
      else setActive((a) => Math.min(a + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (open) setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      if (open && flat[active]) {
        e.preventDefault();
        choose(flat[active]);
      }
    } else if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        close();
      }
    }
  }

  // Render groups into one listbox, tracking a running option index for
  // keyboard highlighting.
  let idx = -1;
  const items: ReactNode[] = display.flatMap((g) => {
    const out: ReactNode[] = [];
    if (g.source)
      out.push(
        <li key={`lbl:${g.source}`} className={styles.groupLabel} role="presentation">
          {g.source}
        </li>,
      );
    for (const n of g.names) {
      idx += 1;
      const i = idx;
      const selected = n === value;
      out.push(
        <li
          key={n}
          data-idx={i}
          role="option"
          aria-selected={selected}
          className={`${styles.option} ${i === active ? styles.active : ""} ${
            selected ? styles.selected : ""
          }`}
          onMouseEnter={() => setActive(i)}
          onMouseDown={(e) => {
            e.preventDefault(); // keep focus; don't blur before we select
            choose(n);
          }}
        >
          {n}
        </li>,
      );
    }
    return out;
  });

  return (
    <div className={styles.root} ref={rootRef}>
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls="feature-listbox"
        aria-autocomplete="list"
        className={styles.input}
        value={open ? query : value}
        placeholder={value || "feature…"}
        disabled={disabled}
        title="Feature type — type to filter"
        onFocus={openList}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />
      <button
        type="button"
        className={styles.caret}
        tabIndex={-1}
        aria-label="Toggle feature list"
        disabled={disabled}
        onMouseDown={(e) => {
          e.preventDefault(); // don't steal focus / trigger blur
          if (open) close();
          else {
            inputRef.current?.focus();
            openList();
          }
        }}
      >
        ▾
      </button>
      {open ? (
        <ul
          className={styles.list}
          id="feature-listbox"
          role="listbox"
          ref={listRef}
        >
          {flat.length === 0 ? (
            <li className={styles.empty} aria-disabled>
              No matches
            </li>
          ) : (
            items
          )}
        </ul>
      ) : null}
    </div>
  );
}
