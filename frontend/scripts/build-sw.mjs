/**
 * Builds public/sw.js by injecting a precache manifest into the hand-written runtime.
 *
 * This is the manifest-injection approach - the same idea as Workbox's `injectManifest`, done
 * with the two files this platform actually needs and no build plugin. The routing rules stay in
 * `src/service-worker/strategy.js` where the test suite can import them directly, and this script
 * only supplies the three things that cannot be known until a build exists: the deployed build
 * hash the caches are keyed to, the list of shell assets to precache, and the API origin the
 * worker is allowed to cache alongside its own.
 *
 * It runs as `postbuild`, so `npm run build` produces the worker and `npm run dev` never does.
 * That is deliberate and is documented in the README: a service worker holding onto assets while
 * Next.js is hot-reloading them is a development environment that lies to you, so there is no
 * service worker in development at all.
 */

import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_DIR = join(ROOT, ".next");
const OUT = join(ROOT, "public", "sw.js");

function buildId() {
  const file = join(NEXT_DIR, "BUILD_ID");
  if (existsSync(file)) return readFileSync(file, "utf8").trim();
  // A worker built without a Next build still needs a version, and a timestamp is a correct
  // (if coarser) answer: it changes on every build, which is all the cache key needs.
  return `dev-${Date.now()}`;
}

function buildAssets() {
  const manifest = join(NEXT_DIR, "build-manifest.json");
  if (!existsSync(manifest)) return [];
  const parsed = JSON.parse(readFileSync(manifest, "utf8"));
  const files = new Set([
    ...(parsed.rootMainFiles || []),
    ...(parsed.polyfillFiles || []),
    ...Object.values(parsed.pages || {}).flat(),
  ]);
  // Only the entry chunks and the stylesheet. Route chunks are cached at runtime on first use,
  // which keeps an install from downloading the whole application on a phone tethered to a port.
  return [...files]
    .filter((file) => file.endsWith(".js") || file.endsWith(".css"))
    .map((file) => `/_next/${file}`);
}

function brandAssets() {
  const iconDir = join(ROOT, "public", "icons");
  if (!existsSync(iconDir)) return [];
  return readdirSync(iconDir)
    .filter((file) => file.endsWith(".png"))
    .map((file) => `/icons/${file}`);
}

function apiOrigin() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!configured) return "";
  try {
    return new URL(configured).origin;
  } catch {
    return "";
  }
}

/** Inlines a module: its `export` keywords stripped, its imports removed. */
function inline(relativePath) {
  const source = readFileSync(join(ROOT, relativePath), "utf8");
  return source
    .replace(/^import[^;]+;$/gm, "")
    .replace(/^export\s+(const|function|async function|let|class)\s/gm, "$1 ")
    .replace(/^export\s*\{[^}]*\};?$/gm, "");
}

const version = buildId();
const manifest = [
  // The offline route first: it is the one asset whose absence would be felt immediately.
  "/offline",
  "/manifest.webmanifest",
  ...brandAssets(),
  ...buildAssets(),
];

const header = `/**
 * GENERATED FILE - do not edit.
 *
 * Built by scripts/build-sw.mjs from src/service-worker/strategy.js and
 * src/service-worker/runtime.js. Edit those, then run \`npm run build\`.
 *
 * Build: ${version}
 */
const CACHE_VERSION = ${JSON.stringify(version)};
const API_ORIGIN = ${JSON.stringify(apiOrigin())};
const PRECACHE_MANIFEST = ${JSON.stringify([...new Set(manifest)], null, 2)};
`;

writeFileSync(
  OUT,
  [header, inline("src/service-worker/strategy.js"), inline("src/service-worker/runtime.js")].join(
    "\n",
  ),
);

process.stdout.write(
  `service worker written to public/sw.js (build ${version}, ${manifest.length} precached)\n`,
);
