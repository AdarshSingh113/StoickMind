// Renders the illustrated product packshots (800x800 JPEG) used by the store, the chat cards and the dashboard.
// The images are committed, so this only runs when the catalogue changes:
//   .venv/bin/python -m kotler.seed.images > /tmp/catalog.json
//   NODE_PATH=$(npm root -g) node scripts/product_images.mjs /tmp/catalog.json kotler/web/media/products
import { createRequire } from "node:module";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright");
const [catalogPath, outDir] = process.argv.slice(2);
const products = JSON.parse(readFileSync(catalogPath, "utf8"));
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Fonts are embedded as data URLs: a page created with setContent() may not load file:// fonts.
const font = (p) => `data:font/woff2;base64,${readFileSync(resolve(root, p)).toString("base64")}`;

// ---- colour helpers -------------------------------------------------------------------------------
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mix = (h, target, t) => "#" + hex(h).map((c, i) => Math.round(c + (target[i] - c) * t).toString(16).padStart(2, "0")).join("");
const tint = (h, t) => mix(h, [255, 255, 255], t);
const shade = (h, t) => mix(h, [0, 0, 0], t);
const cyl = (c) => `linear-gradient(90deg, ${shade(c, .28)} 0%, ${c} 16%, ${tint(c, .32)} 36%, ${tint(c, .12)} 50%, ${c} 70%, ${shade(c, .34)} 100%)`;
const metal = `linear-gradient(90deg, #8d8f94 0%, #d9dbdf 22%, #f7f7f8 40%, #c3c5ca 64%, #7d7f84 100%)`;
const gold = `linear-gradient(90deg, #8a6a2a 0%, #d4b06a 24%, #f6e3b0 42%, #c49a4c 66%, #7a5b20 100%)`;

const label = (p, { w, size = 22, pad = 16, small = false } = {}) => `
  <div class="label" style="width:${w}px;padding:${pad}px ${pad - 2}px">
    <div class="brand" style="font-size:${small ? 9 : 12}px">GLOW &amp; CO.</div>
    <div class="pname" style="font-size:${size}px">${p.name.replace(/&/g, "&amp;")}</div>
    <div class="size" style="font-size:${small ? 10 : 13}px">${p.size}</div>
  </div>`;

const part = (style, inner = "") => `<div class="part" style="${style}">${inner}</div>`;
const stack = (parts) => `<div class="stack">${parts.join("")}</div>`;

const SHAPES = {
  tube: (p) => stack([
    part(`width:236px;height:30px;border-radius:6px;background:repeating-linear-gradient(90deg,${shade(p.main, .2)} 0 6px,${tint(p.main, .1)} 6px 12px)`),
    part(`width:226px;height:390px;border-radius:12px 12px 34px 34px;background:${cyl(p.main)}`, label(p, { w: 178, size: 21 })),
    part(`width:150px;height:84px;border-radius:10px 10px 18px 18px;background:${cyl(shade(p.main, .45))}`),
  ]),
  slimtube: (p) => stack([
    part(`width:150px;height:26px;border-radius:5px;background:repeating-linear-gradient(90deg,${shade(p.main, .2)} 0 5px,${tint(p.main, .1)} 5px 10px)`),
    part(`width:142px;height:340px;border-radius:10px 10px 26px 26px;background:${cyl(p.main)}`, label(p, { w: 112, size: 15, pad: 11, small: true })),
    part(`width:46px;height:76px;border-radius:6px 6px 22px 22px;background:${metal}`),
  ]),
  jar: (p) => stack([
    part(`width:372px;height:92px;border-radius:18px 18px 8px 8px;background:${cyl(shade(p.main, .35))};box-shadow:inset 0 -8px 0 ${shade(p.main, .5)}`),
    part(`width:390px;height:236px;border-radius:14px 14px 56px 56px;background:${cyl(tint(p.main, .78))}`, label(p, { w: 300, size: 24 })),
  ]),
  minijar: (p) => stack([
    part(`width:258px;height:74px;border-radius:16px 16px 6px 6px;background:${cyl(p.main)};box-shadow:inset 0 -7px 0 ${shade(p.main, .3)}`),
    part(`width:272px;height:178px;border-radius:12px 12px 46px 46px;background:${cyl(tint(p.main, .82))}`, label(p, { w: 210, size: 19, pad: 13 })),
  ]),
  dropper: (p) => stack([
    part(`width:76px;height:112px;border-radius:38px 38px 14px 14px;background:${cyl("#2a2a2c")}`),
    part(`width:124px;height:64px;border-radius:8px;background:${gold}`),
    part(`width:256px;height:336px;border-radius:64px 64px 32px 32px;background:${cyl(p.main)};opacity:.96`,
      `<div class="glass"></div>${label(p, { w: 190, size: 20, pad: 14 })}`),
  ]),
  bottle: (p) => stack([
    part(`width:118px;height:92px;border-radius:14px 14px 6px 6px;background:${cyl("#f3efe9")}`),
    part(`width:96px;height:26px;background:${cyl(shade(p.main, .2))}`),
    part(`width:236px;height:430px;border-radius:52px 52px 30px 30px;background:${cyl(tint(p.main, .55))}`, label(p, { w: 180, size: 21 })),
  ]),
  pump: (p) => stack([
    part(`width:150px;height:30px;border-radius:14px 30px 6px 6px;background:${cyl("#f3efe9")};transform:translateX(34px)`),
    part(`width:56px;height:66px;border-radius:6px;background:${cyl("#ece7e0")}`),
    part(`width:116px;height:46px;border-radius:12px 12px 4px 4px;background:${cyl(shade(p.main, .3))}`),
    part(`width:252px;height:400px;border-radius:52px 52px 30px 30px;background:${cyl(p.main)}`, label(p, { w: 192, size: 21 })),
  ]),
  balm: (p) => stack([
    part(`width:126px;height:180px;border-radius:22px 22px 6px 6px;background:${cyl(shade(p.main, .15))}`),
    part(`width:130px;height:10px;background:${metal}`),
    part(`width:126px;height:228px;border-radius:6px 6px 22px 22px;background:${cyl(tint(p.main, .78))}`, label(p, { w: 104, size: 13, pad: 9, small: true })),
  ]),
  box: (p) => stack([
    part(`width:488px;height:76px;border-radius:20px 20px 6px 6px;background:${cyl(shade(p.main, .2))}`,
      `<div class="ribbon" style="height:76px;background:${tint(p.main, .82)}"></div>`),
    part(`width:470px;height:300px;border-radius:6px 6px 22px 22px;background:${cyl(p.main)}`,
      `<div class="ribbon" style="height:300px;background:${tint(p.main, .82)}"></div>
       <div style="position:absolute;right:30px;top:50%;transform:translateY(-50%)">${label(p, { w: 236, size: 22 })}</div>`),
  ]),
};

const page = (p) => `<!doctype html><html><head><meta charset="utf-8"><style>
  @font-face { font-family: Jakarta; src: url("${font("frontend/node_modules/@fontsource-variable/plus-jakarta-sans/files/plus-jakarta-sans-latin-wght-normal.woff2")}"); font-weight: 200 800; }
  @font-face { font-family: Inter; src: url("${font("frontend/public/fonts/inter-latin-600-normal.woff2")}"); font-weight: 600; }
  * { box-sizing: border-box; margin: 0; }
  body { width: 800px; height: 800px; }
  .stage { position: relative; width: 800px; height: 800px; overflow: hidden;
    background: radial-gradient(circle at 50% 46%, ${p.light} 0 270px, ${tint(p.light, .45)} 270px 330px, #fbf9f6 330px); }
  .floor { position: absolute; left: 50%; bottom: 92px; width: 440px; height: 44px; transform: translateX(-50%);
    border-radius: 50%; background: radial-gradient(ellipse, rgba(40,24,8,.22), rgba(40,24,8,0) 70%); }
  .stack { position: absolute; left: 50%; bottom: 112px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; }
  .part { position: relative; display: flex; align-items: center; justify-content: center; }
  .glass { position: absolute; left: 30px; top: 30px; width: 26px; height: 240px; border-radius: 13px; background: rgba(255,255,255,.28); }
  .ribbon { position: absolute; left: 90px; top: 0; width: 42px; }
  .label { background: #fffdf9; border-radius: 12px; box-shadow: 0 2px 6px rgba(0,0,0,.12); text-align: center; }
  .brand { font-family: Inter; font-weight: 600; letter-spacing: .26em; color: #8a7f72; }
  .pname { font-family: Jakarta; font-weight: 800; line-height: 1.12; letter-spacing: -.01em; color: #16130f; margin: 6px 0 5px; text-wrap: balance; }
  .size { font-family: Inter; font-weight: 600; color: #8a7f72; }
</style></head><body><div class="stage"><div class="floor"></div>${SHAPES[p.container](p)}</div></body></html>`;

mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const tab = await browser.newPage({ viewport: { width: 800, height: 800 } });
for (const p of products) {
  await tab.setContent(page(p), { waitUntil: "load" });
  await tab.evaluate(() => document.fonts.ready);
  const ok = await tab.evaluate(() => document.fonts.check("800 20px Jakarta") && document.fonts.check("600 12px Inter"));
  if (!ok) throw new Error("fonts did not load");
  await tab.locator(".stage").screenshot({ path: `${outDir}/${p.slug}.jpg`, type: "jpeg", quality: 86 });
  process.stdout.write(".");
}
await browser.close();
console.log(`\n${products.length} images written to ${outDir}`);
