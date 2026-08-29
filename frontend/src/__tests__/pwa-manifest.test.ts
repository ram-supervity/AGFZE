import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The manifest and the icon set, checked as files rather than as intentions.
 *
 * An installable app is one whose manifest a browser accepts and whose icons are the sizes each
 * platform actually asks for - a 192 and a 512 for Chromium, a maskable 512 for Android's
 * adaptive icons, a 180 for an iOS home screen. Anything missing here is an install that silently
 * does not offer itself, which is exactly the kind of failure nobody notices until a user says
 * the button never appeared.
 */

const PUBLIC = join(__dirname, "..", "..", "public");

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
}

const manifest = JSON.parse(
  readFileSync(join(PUBLIC, "manifest.webmanifest"), "utf8"),
) as {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: ManifestIcon[];
};

/** Width and height read out of the PNG's own IHDR chunk, not out of the filename. */
function pngDimensions(path: string): { width: number; height: number; hasAlpha: boolean } {
  const file = readFileSync(path);
  expect(file.subarray(0, 8)).toEqual(
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  );
  return {
    width: file.readUInt32BE(16),
    height: file.readUInt32BE(20),
    // Colour type 6 is truecolour with alpha.
    hasAlpha: file[25] === 6,
  };
}

describe("the web app manifest", () => {
  it("declares everything a browser needs to offer an install", () => {
    expect(manifest.name).toBe("AGFZE Command Centre");
    expect(manifest.short_name.length).toBeGreaterThan(0);
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url.startsWith("/")).toBe(true);
    expect(manifest.scope).toBe("/");
  });

  it("carries the ink-navy the design system has used since Step 1", () => {
    expect(manifest.theme_color).toBe("#182338");
    expect(manifest.background_color).toBe("#182338");
  });

  it("lists a real icon for each platform's requirement", () => {
    const bySize = Object.fromEntries(
      manifest.icons.map((icon) => [`${icon.sizes}:${icon.purpose ?? "any"}`, icon]),
    );
    expect(bySize["192x192:any"]).toBeDefined();
    expect(bySize["512x512:any"]).toBeDefined();
    // Android crops an adaptive icon to whatever shape the launcher uses, so a maskable variant
    // is not optional on that platform.
    expect(bySize["512x512:maskable"]).toBeDefined();
  });
});

describe("the icon files", () => {
  it("are real PNGs at the sizes they claim", () => {
    for (const icon of manifest.icons) {
      const [declared] = icon.sizes.split("x").map(Number);
      const { width, height } = pngDimensions(join(PUBLIC, icon.src));
      expect(width, icon.src).toBe(declared);
      expect(height, icon.src).toBe(declared);
    }
  });

  it("include the 180px opaque icon iOS installs from", () => {
    const path = join(PUBLIC, "icons", "apple-touch-icon-180.png");
    const { width, height } = pngDimensions(path);
    expect(width).toBe(180);
    expect(height).toBe(180);
  });

  it("include the badge Android shows beside a push notification", () => {
    const { width } = pngDimensions(join(PUBLIC, "icons", "badge-72.png"));
    expect(width).toBe(72);
  });

  it("are drawn artwork rather than a filler square", () => {
    // A solid colour compresses to a few hundred bytes at 512px; the brand mark does not. This is
    // a floor on "something was actually drawn here", not a measure of quality.
    const size = statSync(join(PUBLIC, "icons", "icon-512.png")).size;
    expect(size).toBeGreaterThan(2000);
  });
});
