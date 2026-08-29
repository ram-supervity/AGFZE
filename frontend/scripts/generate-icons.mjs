/**
 * Draws the PWA icon set from the same mark the application draws in its header.
 *
 * `src/components/layout/brand-mark.tsx` is an SVG in a 32-unit viewBox: an ink-navy rounded
 * square carrying three stacked copper bars. This script rasterises that exact geometry - the
 * same coordinates, the same palette, the same opacities - so the icon on a home screen is the
 * wordmark the user has been looking at since  rather than a square somebody drew twice.
 *
 * It encodes PNG by hand (zlib is in Node's standard library) rather than pulling an image
 * library in for four files. Everything is drawn at 4x and box-filtered down, which is what gives
 * the rounded corner and the diagonal bar edges a clean edge at 192px.
 *
 *   node scripts/generate-icons.mjs      (or: make icons)
 */

import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");

// The palette, unchanged since 's design system.
const INK_NAVY = [0x18, 0x23, 0x38];
const COPPER = [0xa7, 0x5d, 0x35];
const PAPER = [0xff, 0xff, 0xff];

// The brand mark's own geometry, in its 32-unit viewBox.
const VIEWBOX = 32;
const CORNER_RADIUS = 7;
const BARS = [
  { points: [[13.5, 9], [18.5, 9], [21, 13], [11, 13]], opacity: 1 },
  { points: [[11.5, 14.5], [20.5, 14.5], [23, 18.5], [9, 18.5]], opacity: 0.85 },
  { points: [[9.5, 20], [22.5, 20], [25, 24], [7, 24]], opacity: 0.7 },
];

const SUPERSAMPLE = 4;

function blend(foreground, background, alpha) {
  return foreground.map((channel, index) =>
    Math.round(channel * alpha + background[index] * (1 - alpha)),
  );
}

function insideRoundedSquare(x, y, size, radius) {
  if (x < 0 || y < 0 || x > size || y > size) return false;
  const cx = Math.min(Math.max(x, radius), size - radius);
  const cy = Math.min(Math.max(y, radius), size - radius);
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= radius * radius;
}

function insidePolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    const intersects =
      yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

/**
 * @param {number} size          pixel width and height of the finished icon
 * @param {object} options
 * @param {boolean} options.maskable  full-bleed navy with the mark inside Android's safe zone
 * @param {boolean} options.opaque    no transparency at all (iOS composites nothing)
 * @param {number[]} options.mark     the bar colour, so the push badge can be drawn in paper
 */
function render(size, { maskable = false, opaque = false, mark = COPPER } = {}) {
  const supersampled = size * SUPERSAMPLE;
  const pixels = Buffer.alloc(size * size * 4);

  // The mark occupies the whole canvas normally. On a maskable icon it is scaled so that its
  // drawn content - the bars span 18 of 32 units across and 15 down, not the whole box - sits
  // inside Android's safe circle, the central 80% the launcher promises never to crop.
  const markScale = maskable ? 0.85 : 1;
  const offset = ((1 - markScale) / 2) * supersampled;
  const unit = (supersampled * markScale) / VIEWBOX;

  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;

      for (let sy = 0; sy < SUPERSAMPLE; sy += 1) {
        for (let sx = 0; sx < SUPERSAMPLE; sx += 1) {
          const deviceX = px * SUPERSAMPLE + sx + 0.5;
          const deviceY = py * SUPERSAMPLE + sy + 0.5;
          const markX = (deviceX - offset) / unit;
          const markY = (deviceY - offset) / unit;

          let colour = null;
          let alpha = 0;

          // A maskable or opaque icon is navy edge to edge, so the launcher's own mask - or
          // iOS, which composites nothing - can cut any shape without exposing a corner. The
          // standard icon keeps the brand mark's rounded square and its transparency.
          if (maskable || opaque || insideRoundedSquare(markX, markY, VIEWBOX, CORNER_RADIUS)) {
            colour = INK_NAVY;
            alpha = 1;
          }

          if (colour) {
            for (const bar of BARS) {
              if (insidePolygon(markX, markY, bar.points)) {
                colour = blend(mark, INK_NAVY, bar.opacity);
                break;
              }
            }
            r += colour[0];
            g += colour[1];
            b += colour[2];
            a += alpha * 255;
          }
        }
      }

      const samples = SUPERSAMPLE * SUPERSAMPLE;
      const index = (py * size + px) * 4;
      const covered = a / 255;
      pixels[index] = covered ? Math.round(r / covered) : 0;
      pixels[index + 1] = covered ? Math.round(g / covered) : 0;
      pixels[index + 2] = covered ? Math.round(b / covered) : 0;
      pixels[index + 3] = Math.round(a / samples);
    }
  }
  return pixels;
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, checksum]);
}

function encodePng(size, pixels) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // truecolour with alpha
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    pixels.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const ICONS = [
  { file: "icon-192.png", size: 192, options: {} },
  { file: "icon-512.png", size: 512, options: {} },
  // Android's adaptive-icon system crops to whatever shape the launcher uses.
  { file: "icon-maskable-512.png", size: 512, options: { maskable: true } },
  // iOS never masks and never composites: the home-screen icon has to be square and opaque, or
  // it is drawn on black.
  { file: "apple-touch-icon-180.png", size: 180, options: { opaque: true } },
  // The monochrome badge Android shows in the status bar beside a push notification.
  { file: "badge-72.png", size: 72, options: { opaque: true, mark: PAPER } },
];

mkdirSync(OUT_DIR, { recursive: true });
for (const icon of ICONS) {
  const png = encodePng(icon.size, render(icon.size, icon.options));
  writeFileSync(join(OUT_DIR, icon.file), png);
  const digest = createHash("sha256").update(png).digest("hex").slice(0, 12);
  process.stdout.write(`${icon.file}  ${icon.size}x${icon.size}  ${png.length}B  ${digest}\n`);
}
