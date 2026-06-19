// Tiny block-level Markdown renderer tailored for the bundled docs.
// Handles: ATX headings (# ## ###), paragraphs, fenced code blocks
// (```lang), inline code (`), bullet lists (-), GFM-style tables (|),
// horizontal rules (---), links [t](u), bold (**), italic (*).
//
// Not a general-purpose renderer — it covers exactly what `docs/dsl.md`
// uses. If you need more, reach for `react-markdown`.
import { type ReactNode } from "react";
import styles from "./Markdown.module.css";

export function Markdown({ source }: { source: string }) {
  return <div className={styles.md}>{renderBlocks(source)}</div>;
}

type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: string; id: string }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; lang: string; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "hr" }
  | { kind: "table"; header: string[]; align: ("left" | "right" | "center" | null)[]; rows: string[][] };

function renderBlocks(src: string): ReactNode[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Skip blank lines.
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Fenced code block.
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      i++;
      const buf: string[] = [];
      while (i < lines.length && !lines[i].startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // consume closing fence
      blocks.push({ kind: "code", lang, text: buf.join("\n") });
      continue;
    }

    // ATX heading.
    const h = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
    if (h) {
      const level = h[1].length as 1 | 2 | 3;
      const text = h[2];
      blocks.push({ kind: "heading", level, text, id: slug(text) });
      i++;
      continue;
    }

    // Horizontal rule.
    if (/^---+\s*$/.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }

    // Table — needs a header row, a separator row, then body rows.
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s\-:|]+\|[\s\-:|]+$/.test(lines[i + 1])) {
      const header = splitRow(line);
      const align = splitRow(lines[i + 1]).map((c) => {
        const left = c.startsWith(":");
        const right = c.endsWith(":");
        if (left && right) return "center" as const;
        if (right) return "right" as const;
        if (left) return "left" as const;
        return null;
      });
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ kind: "table", header, align, rows });
      continue;
    }

    // Bullet list.
    if (/^\s*-\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*-\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*-\s+/, ""));
        i++;
      }
      blocks.push({ kind: "list", items });
      continue;
    }

    // Paragraph: gather until a blank line or block boundary.
    const buf: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("```") &&
      !/^#{1,3}\s/.test(lines[i]) &&
      !/^---+\s*$/.test(lines[i]) &&
      !/^\s*-\s+/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "paragraph", text: buf.join(" ") });
  }

  return blocks.map((b, idx) => renderBlock(b, idx));
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderBlock(b: Block, key: number): ReactNode {
  if (b.kind === "heading") {
    const inner = renderInline(b.text);
    if (b.level === 1) return <h1 key={key} id={b.id}>{inner}</h1>;
    if (b.level === 2) return <h2 key={key} id={b.id}>{inner}</h2>;
    return <h3 key={key} id={b.id}>{inner}</h3>;
  }
  if (b.kind === "paragraph") {
    return <p key={key}>{renderInline(b.text)}</p>;
  }
  if (b.kind === "code") {
    return (
      <pre key={key} className={styles.code} data-lang={b.lang || undefined}>
        <code>{b.text}</code>
      </pre>
    );
  }
  if (b.kind === "list") {
    return (
      <ul key={key}>
        {b.items.map((it, i) => (
          <li key={i}>{renderInline(it)}</li>
        ))}
      </ul>
    );
  }
  if (b.kind === "hr") {
    return <hr key={key} />;
  }
  return (
    <div key={key} className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {b.header.map((c, i) => (
              <th key={i} style={alignStyle(b.align[i])}>{renderInline(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {b.rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((c, ci) => (
                <td key={ci} style={alignStyle(b.align[ci])}>{renderInline(c)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function alignStyle(a: "left" | "right" | "center" | null): { textAlign?: "left" | "right" | "center" } {
  return a ? { textAlign: a } : {};
}

// Inline parser: code (`), bold (**), italic (*), links [t](u).
function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  let key = 0;
  let buf = "";
  const flush = () => {
    if (buf) {
      out.push(buf);
      buf = "";
    }
  };

  while (i < text.length) {
    const c = text[i];

    // Inline code.
    if (c === "`") {
      const end = text.indexOf("`", i + 1);
      if (end !== -1) {
        flush();
        out.push(<code key={key++}>{text.slice(i + 1, end)}</code>);
        i = end + 1;
        continue;
      }
    }

    // Bold (**...**) — must check before italic.
    if (c === "*" && text[i + 1] === "*") {
      const end = text.indexOf("**", i + 2);
      if (end !== -1) {
        flush();
        out.push(<strong key={key++}>{renderInline(text.slice(i + 2, end))}</strong>);
        i = end + 2;
        continue;
      }
    }

    // Italic (*...*) — single asterisks, no spaces adjacent.
    if (c === "*") {
      const end = text.indexOf("*", i + 1);
      if (end !== -1 && end > i + 1) {
        flush();
        out.push(<em key={key++}>{renderInline(text.slice(i + 1, end))}</em>);
        i = end + 1;
        continue;
      }
    }

    // Link [text](url).
    if (c === "[") {
      const close = text.indexOf("]", i + 1);
      if (close !== -1 && text[close + 1] === "(") {
        const paren = text.indexOf(")", close + 2);
        if (paren !== -1) {
          flush();
          const label = text.slice(i + 1, close);
          const href = text.slice(close + 2, paren);
          out.push(
            <a key={key++} href={href} target="_blank" rel="noreferrer">
              {renderInline(label)}
            </a>,
          );
          i = paren + 1;
          continue;
        }
      }
    }

    buf += c;
    i++;
  }
  flush();
  return out;
}

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}
