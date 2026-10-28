// The distribution's website, published on GitHub Pages (.github/workflows/pages.yml).
// Names, colours, links and the logo come from ../distro.conf and ../branding,
// the documentation from ../docs and the desktop screenshots from the dots
// submodule, so the site follows a rename like everything else.
import { copyFileSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));

function readConf() {
  const conf = {};
  for (const line of readFileSync(path.join(repoRoot, "distro.conf"), "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)="(.*)"\s*$/);
    if (m) conf[m[1]] = m[2];
  }
  return conf;
}

function distro() {
  const conf = readConf();
  const escape = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const logo = readFileSync(path.join(repoRoot, "branding/logo/logo-mark.svg.in"), "utf8")
    .replace(/@([A-Z0-9_]+)@/g, (m, k) => conf[k] ?? m);
  let outDir = "dist";
  return {
    name: "distro",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    transformIndexHtml(html) {
      return html
        .replace(/%(DISTRO_[A-Z_]+|BRAND_[A-Z0-9_]+)%/g, (m, k) => escape(conf[k] ?? m))
        .replace("%FAVICON%", `data:image/svg+xml,${encodeURIComponent(logo)}`);
    },
    // GitHub Pages answers unknown paths with 404.html: the same app, so
    // /docs/gpu works when opened directly or reloaded.
    closeBundle() {
      copyFileSync(path.join(outDir, "index.html"), path.join(outDir, "404.html"));
    },
  };
}

export default defineConfig({
  // /<repository>/ on GitHub Pages (set by the workflow), / elsewhere.
  base: process.env.BASE_PATH || "/",
  plugins: [react(), tailwindcss(), distro()],
  server: { fs: { allow: [repoRoot] } },
  build: { chunkSizeWarningLimit: 900 },
});
