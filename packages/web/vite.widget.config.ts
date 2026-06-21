import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Builds the embeddable play-view widget as a single self-contained IIFE
// script (dungml-play.js) that exposes `window.DungmlPlay`. React and all CSS
// are bundled in, so a host page needs nothing but one <script> tag.
//
// Run AFTER the SPA build (`npm run build`): the SPA build empties the static
// dir, so this one appends to it with emptyOutDir: false.
const here = fileURLToPath(new URL(".", import.meta.url));
const backendStatic = resolve(here, "../backend/src/dungml_backend/static");

// Lib mode extracts component CSS into a separate file. For a true drop-in
// single script we fold that CSS back into the JS as a runtime <style>.
function inlineCss(): Plugin {
  return {
    name: "dungml-inline-css",
    enforce: "post",
    generateBundle(_options, bundle) {
      let css = "";
      for (const [file, chunk] of Object.entries(bundle)) {
        if (chunk.type === "asset" && file.endsWith(".css")) {
          css +=
            typeof chunk.source === "string"
              ? chunk.source
              : Buffer.from(chunk.source).toString("utf8");
          delete bundle[file];
        }
      }
      if (!css) return;
      const inject =
        `(function(){try{var d=document,s=d.createElement("style");` +
        `s.setAttribute("data-dungml-play","");s.textContent=${JSON.stringify(css)};` +
        `(d.head||d.documentElement).appendChild(s);}catch(e){}})();\n`;
      for (const chunk of Object.values(bundle)) {
        if (chunk.type === "chunk" && chunk.isEntry) {
          chunk.code = inject + chunk.code;
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), inlineCss()],
  define: {
    // React reads this; lib builds don't get the SPA's automatic replacement.
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: backendStatic,
    emptyOutDir: false,
    cssCodeSplit: false,
    lib: {
      entry: resolve(here, "src/widget.tsx"),
      formats: ["iife"],
      name: "DungmlPlay",
      fileName: () => "dungml-play.js",
    },
  },
});
