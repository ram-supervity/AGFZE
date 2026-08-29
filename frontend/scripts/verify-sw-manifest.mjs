/**
 * Checks the built service worker's precache manifest against the build output it was written
 * from, and exits non-zero if the two have drifted.
 *
 * The failure this exists to catch is quiet and nasty. `scripts/build-sw.mjs` reads
 * `.next/build-manifest.json` and bakes a list of hashed chunk URLs into `public/sw.js`. If that
 * file is stale - a worker from a previous build committed by accident, a build that failed
 * halfway, an asset renamed - the worker installs against URLs that 404. Nothing fails loudly:
 * install swallows a missing asset by design so one bad URL cannot cost the whole offline page,
 * so the app simply becomes less and less useful offline while every build stays green.
 *
 * So this runs in CI, after the build, and blocks the deploy:
 *
 *   - the worker exists and was written from *this* build (its CACHE_VERSION is the BUILD_ID);
 *   - every precached URL resolves to a file that is actually in the build output or in public/;
 *   - the offline route is precached, because it is the one asset whose absence is felt at once;
 *   - the API origin baked in matches the one this build was configured with.
 *
 * Usage: node scripts/verify-sw-manifest.mjs
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_DIR = join(ROOT, ".next");
const SW = join(ROOT, "public", "sw.js");

const problems = [];

function fail(message) {
  problems.push(message);
}

function readWorker() {
  if (!existsSync(SW)) {
    fail("public/sw.js does not exist. Run `npm run build`, which writes it as a postbuild step.");
    return null;
  }
  return readFileSync(SW, "utf8");
}

function extract(source, name) {
  const match = source.match(new RegExp(`const ${name} = ([\\s\\S]*?);\\n`));
  if (!match) {
    fail(`public/sw.js does not declare ${name}. The build script did not produce it.`);
    return null;
  }
  try {
    return JSON.parse(match[1]);
  } catch {
    fail(`public/sw.js declares ${name} as something that is not valid JSON.`);
    return null;
  }
}

/** Where a precached URL should be found on disk. Routes are served, not stored, so they pass. */
function locate(url) {
  if (url.startsWith("/_next/")) return join(NEXT_DIR, url.slice("/_next/".length));
  return join(ROOT, "public", url);
}

const ROUTE_URLS = new Set(["/offline"]);

const source = readWorker();
if (source) {
  const version = extract(source, "CACHE_VERSION");
  const manifest = extract(source, "PRECACHE_MANIFEST");
  const apiOrigin = extract(source, "API_ORIGIN");

  const buildIdFile = join(NEXT_DIR, "BUILD_ID");
  if (!existsSync(buildIdFile)) {
    fail(".next/BUILD_ID is missing, so there is no build to verify this worker against.");
  } else {
    const buildId = readFileSync(buildIdFile, "utf8").trim();
    if (version !== buildId) {
      fail(
        `public/sw.js was built from ${version}, but the current build is ${buildId}. ` +
          "The worker is stale - rebuild rather than shipping it.",
      );
    }
  }

  if (Array.isArray(manifest)) {
    if (!manifest.includes("/offline")) {
      fail("The precache manifest does not include /offline, the one asset offline depends on.");
    }
    const missing = manifest.filter(
      (url) => !ROUTE_URLS.has(url) && !existsSync(locate(url)),
    );
    for (const url of missing) {
      fail(`Precached asset ${url} is not present in the build output.`);
    }
    if (manifest.length === 0) fail("The precache manifest is empty.");
  }

  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configured) {
    const expected = new URL(configured).origin;
    if (apiOrigin !== expected) {
      fail(
        `The worker was built against API origin "${apiOrigin}" but this environment configures ` +
          `"${expected}". Rebuild with the deployment's own value.`,
      );
    }
  }
}

if (problems.length > 0) {
  process.stderr.write(
    `service-worker manifest verification failed:\n${problems.map((p) => `  - ${p}`).join("\n")}\n`,
  );
  process.exit(1);
}

process.stdout.write("service-worker precache manifest verified against the current build\n");
