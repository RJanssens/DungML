// Monarch tokenizer and theme for the .dmap DSL.
//
// The token classes here are mapped to colors in the `dmapTheme` below.
// Both should round-trip through Monaco's `editor.defineTheme` and
// `languages.setMonarchTokensProvider`.
import type * as monaco from "monaco-editor";

export const LANGUAGE_ID = "dmap";

// Top-level structural keywords (`map`, `room`, …) get the strongest
// emphasis. Property keywords (`width`, `at`, `rotate`, …) are
// secondary.
const STRUCTURAL = [
  "map",
  "grid",
  "renderer",
  "theme",
  "feature_def",
  "feature",
  "room",
  "corridor",
  "slice",
  "door",
  "window",
  "marker",
  "text",
  "area",
  "line_feature",
  "layer",
  "include",
];

const PROPERTIES = [
  "cell",
  "units",
  "bounds",
  "origin",
  "shape",
  "background",
  "line_style",
  "allow_overlap",
  "outline",
  "overlay",
  "description",
  "dm_notes",
  "name",
  "label",
  "segment",
  "connects",
  "type",
  "state",
  "facing",
  "width",
  "height",
  "radius",
  "size",
  "rotate",
  "scale",
  "color",
  "stroke",
  "offset",
  "fill",
  "in",
  "kind",
  "align",
  "tag",
  "initial",
  "image",
  "kind",
];

// "Shape" / structural sub-keywords.
const SHAPES = [
  "circle",
  "rect",
  "polygon",
  "boundary",
  "line",
  "arc",
  "segment",
];

// "Connector" keywords inside expressions — `at`, `to`, `from`, …
const CONNECTORS = [
  "at",
  "to",
  "from",
  "via",
  "from-angle",
  "to-angle",
  "sweep",
  "start",
  "center",
  "hidden",
];

// Enum-like value words. Listed separately so they can color differently
// from regular identifiers when used unquoted.
const VALUES = [
  "top-left",
  "bottom-left",
  "ccw",
  "cw",
  "solid",
  "dashed",
  "dotted",
  "organic",
  "ruined",
  "trail",
  "bars",
  "curtain",
  "barred",
  "wooden",
  "iron",
  "stone",
  "arch",
  "secret",
  "open",
  "closed",
  "locked",
  "north",
  "south",
  "east",
  "west",
  "px",
  "feet",
  "meters",
  "m",
  "ft",
  "dark",
  "light",
  "party",
  "ally",
  "npc",
  "enemy",
  "boss",
  "neutral",
  "unknown",
  "lava",
  "pit",
  "chasm",
  "mud",
  "acid",
  "ice",
  "blood",
  "slime",
  "swamp",
];

export function makeLanguage(): monaco.languages.IMonarchLanguage {
  return {
    defaultToken: "",
    ignoreCase: false,
    tokenPostfix: ".dmap",

    structural: STRUCTURAL,
    properties: PROPERTIES,
    shapes: SHAPES,
    connectors: CONNECTORS,
    values: VALUES,

    tokenizer: {
      root: [
        // Comments
        [/#.*$/, "comment"],

        // Triple-quoted string
        [/"""/, { token: "string.quote", next: "@triple" }],

        // Regular string
        [/"([^"\\]|\\.)*$/, "string.invalid"],
        [/"/, { token: "string.quote", next: "@string" }],

        // Numbers (with optional sign, decimal)
        [/-?\d+\.\d+/, "number.float"],
        [/-?\d+/, "number"],

        // Dotted refs like `room.foo` or `corridor.bar` — color the prefix
        // as a "namespace" and the rest as a member identifier.
        [
          /\b(room|corridor|feature_def|layer)(\.)([a-zA-Z_][a-zA-Z0-9_-]*)/,
          ["keyword.ref-kind", "delimiter", "identifier.ref"],
        ],

        // Identifiers — checked against keyword sets in priority order.
        [
          /[a-zA-Z_][a-zA-Z0-9_-]*/,
          {
            cases: {
              "@structural": "keyword.structural",
              "@properties": "keyword.property",
              "@shapes": "keyword.shape",
              "@connectors": "keyword.connector",
              "@values": "keyword.value",
              "@default": "identifier",
            },
          },
        ],

        // Geometry tokens — the literal `x` in `5 x 3`.
        [/\bx\b/, "operator.dimension"],

        // Delimiters / punctuation
        [/[{}()]/, "@brackets"],
        [/[,]/, "delimiter"],

        // Whitespace
        [/\s+/, ""],
      ],

      string: [
        [/[^\\"]+/, "string"],
        [/\\./, "string.escape"],
        [/"/, { token: "string.quote", next: "@pop" }],
      ],

      triple: [
        [/[^"]+/, "string"],
        [/"""/, { token: "string.quote", next: "@pop" }],
        [/"/, "string"],
      ],
    },
  } as unknown as monaco.languages.IMonarchLanguage;
}

export const languageConfig: monaco.languages.LanguageConfiguration = {
  comments: { lineComment: "#" },
  brackets: [
    ["{", "}"],
    ["(", ")"],
  ],
  autoClosingPairs: [
    { open: "{", close: "}" },
    { open: "(", close: ")" },
    { open: '"', close: '"' },
  ],
  surroundingPairs: [
    { open: "{", close: "}" },
    { open: "(", close: ")" },
    { open: '"', close: '"' },
  ],
};

// Theme — designed for a paper-ish background. Token rules use the
// suffixed classes from the tokenizer (e.g. "keyword.structural.dmap").
export function defineTheme(monaco: typeof import("monaco-editor")): string {
  const id = "dmap-paper";
  monaco.editor.defineTheme(id, {
    base: "vs",
    inherit: true,
    rules: [
      { token: "comment", foreground: "8a8a85", fontStyle: "italic" },
      { token: "string", foreground: "9b5b2d" },
      { token: "string.quote", foreground: "9b5b2d" },
      { token: "string.escape", foreground: "9b5b2d", fontStyle: "bold" },
      { token: "number", foreground: "2d6985" },
      { token: "number.float", foreground: "2d6985" },
      { token: "keyword.structural", foreground: "6b3e2e", fontStyle: "bold" },
      { token: "keyword.property", foreground: "4a4f37" },
      { token: "keyword.shape", foreground: "3f6043", fontStyle: "bold" },
      { token: "keyword.connector", foreground: "6f6457" },
      { token: "keyword.value", foreground: "8a4a78" },
      { token: "keyword.ref-kind", foreground: "6b3e2e" },
      { token: "identifier.ref", foreground: "2f2f2f", fontStyle: "italic" },
      { token: "identifier", foreground: "1a1a1a" },
      { token: "operator.dimension", foreground: "8a8a85" },
      { token: "delimiter", foreground: "5b5b58" },
    ],
    colors: {
      "editor.background": "#fdfaf3",
      "editor.foreground": "#1a1a1a",
      "editorLineNumber.foreground": "#bcb6a8",
      "editorLineNumber.activeForeground": "#5b5b58",
      "editor.lineHighlightBackground": "#f3eddc",
      "editorCursor.foreground": "#6b3e2e",
      "editor.selectionBackground": "#e5dcc1",
      "editorIndentGuide.background1": "#ede5d2",
      "editorIndentGuide.activeBackground1": "#cfc9bd",
      "editorBracketMatch.background": "#e5dcc1",
      "editorBracketMatch.border": "#6b3e2e",
    },
  });
  return id;
}
