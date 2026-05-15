// Rasterize ``app-icon.svg`` into PNGs for the web app manifest and Apple touch.
// Run via ``pnpm run build`` (after ``pnpm install``).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const svgPath = path.join(
  repoRoot,
  "web_ui",
  "static",
  "web_ui",
  "icons",
  "app-icon.svg",
);
const outDir = path.join(repoRoot, "web_ui", "static", "web_ui", "icons");

const bg = { r: 245, g: 245, b: 245, alpha: 1 };

async function main() {
  const input = fs.readFileSync(svgPath);
  for (const size of [192, 512]) {
    const outPath = path.join(outDir, `icon-${size}.png`);
    await sharp(input)
      .resize(size, size, { fit: "contain", background: bg })
      .png()
      .toFile(outPath);
    console.log(`[pwa-icons] wrote ${path.relative(repoRoot, outPath)}`);
  }
}

void main();
