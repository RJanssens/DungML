// Wrapper around @monaco-editor/react that registers the .dmap language
// once, exposes a marker setter for diagnostics, and forwards Cmd+S.
import Editor, { OnMount, type Monaco } from "@monaco-editor/react";
import { useCallback, useEffect, useRef } from "react";
import type * as monaco from "monaco-editor";
import {
  LANGUAGE_ID,
  defineTheme,
  languageConfig,
  makeLanguage,
} from "../lib/dmapLanguage";
import type { Diagnostic } from "../lib/types";

let registered = false;

function registerOnce(monacoNs: Monaco) {
  if (registered) return;
  registered = true;
  monacoNs.languages.register({ id: LANGUAGE_ID, extensions: [".dmap"] });
  monacoNs.languages.setMonarchTokensProvider(LANGUAGE_ID, makeLanguage());
  monacoNs.languages.setLanguageConfiguration(LANGUAGE_ID, languageConfig);
}

export interface MonacoEditorProps {
  value: string;
  onChange: (v: string) => void;
  diagnostics?: Diagnostic[];
  onSave?: () => void;
  /** Reveal a position when this changes — `nonce` forces re-trigger. */
  goto?: { line: number; column?: number; nonce: number } | null;
}

export function MonacoEditor({
  value,
  onChange,
  diagnostics = [],
  onSave,
  goto = null,
}: MonacoEditorProps) {
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);

  // Reveal + place the cursor whenever `goto` changes (jump-to-definition).
  useEffect(() => {
    const ed = editorRef.current;
    if (!ed || !goto || goto.line <= 0) return;
    const pos = { lineNumber: goto.line, column: goto.column ?? 1 };
    ed.revealLineInCenter(goto.line);
    ed.setPosition(pos);
    ed.focus();
  }, [goto]);

  const setMarkers = useCallback((diags: Diagnostic[]) => {
    const editor = editorRef.current;
    const monacoNs = monacoRef.current;
    if (!editor || !monacoNs) return;
    const model = editor.getModel();
    if (!model) return;
    const markers: monaco.editor.IMarkerData[] = diags
      .filter((d) => d.line > 0)
      .map((d) => ({
        severity:
          d.severity === "error"
            ? monacoNs.MarkerSeverity.Error
            : monacoNs.MarkerSeverity.Warning,
        message: d.message,
        startLineNumber: d.line,
        startColumn: Math.max(1, d.column),
        endLineNumber: d.end_line > 0 ? d.end_line : d.line,
        endColumn: Math.max(
          d.column + 1,
          d.end_column > 0 ? d.end_column : d.column + 1,
        ),
      }));
    monacoNs.editor.setModelMarkers(model, "dmap", markers);
  }, []);

  // Re-apply markers whenever diagnostics change.
  if (editorRef.current && monacoRef.current) {
    setMarkers(diagnostics);
  }

  const handleMount: OnMount = (editor, monacoNs) => {
    editorRef.current = editor;
    monacoRef.current = monacoNs;
    registerOnce(monacoNs);
    const themeId = defineTheme(monacoNs as unknown as typeof import("monaco-editor"));
    monacoNs.editor.setTheme(themeId);
    const model = editor.getModel();
    if (model) monacoNs.editor.setModelLanguage(model, LANGUAGE_ID);
    setMarkers(diagnostics);

    if (onSave) {
      editor.addCommand(
        monacoNs.KeyMod.CtrlCmd | monacoNs.KeyCode.KeyS,
        () => onSave(),
      );
    }
  };

  return (
    <Editor
      height="100%"
      defaultLanguage={LANGUAGE_ID}
      language={LANGUAGE_ID}
      value={value}
      onChange={(v) => onChange(v ?? "")}
      onMount={handleMount}
      options={{
        fontSize: 13,
        fontFamily:
          'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontLigatures: false,
        minimap: { enabled: false },
        automaticLayout: true, // reflow when the pane is resized (split drag)
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        wordWrap: "off",
        lineNumbersMinChars: 3,
        renderLineHighlight: "line",
        padding: { top: 16, bottom: 16 },
        tabSize: 2,
      }}
    />
  );
}
