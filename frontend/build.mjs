// Bundle Three.js with the spectator script so the served experience works offline.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));
await build({
  entryPoints: [resolve(root, "app.js")],
  outfile: resolve(root, "../backend/app/static/app.bundle.js"),
  bundle: true,
  minify: true,
  sourcemap: false,
  target: ["es2020"],
  legalComments: "none",
});
console.log("Built the Three.js spectator bundle for FastAPI.");
