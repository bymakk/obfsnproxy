// Cross-language parity test: load dist/rkn.bloom (built by build_bloom.py) and verify
// the JS hashing (identical to the extension's useRknList.ts) agrees with the Python
// generator. Run: node scripts/verify_parity.mjs
import { readFileSync } from "node:fs";

const MAGIC = 0x4d4f4c42; // "BLOM" LE

function parse(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (dv.getUint32(0, true) !== MAGIC) throw new Error("bad magic");
  if (dv.getUint32(4, true) !== 1) throw new Error("bad version");
  const m = dv.getUint32(8, true);
  const k = dv.getUint32(12, true);
  const n = dv.getUint32(16, true);
  const bits = new Uint8Array(buf.buffer, buf.byteOffset + 20, buf.byteLength - 20);
  return { m, k, n, bits };
}

function fnv1a32(bytes) {
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i++) h = Math.imul(h ^ bytes[i], 0x01000193) >>> 0;
  return h >>> 0;
}
function djb2a(bytes) {
  let h = 5381;
  for (let i = 0; i < bytes.length; i++) h = (Math.imul(h, 33) ^ bytes[i]) >>> 0;
  return h >>> 0;
}
function contains(f, domain) {
  const bytes = new TextEncoder().encode(domain);
  const h1 = fnv1a32(bytes);
  const h2 = (djb2a(bytes) | 1) >>> 0;
  for (let i = 0; i < f.k; i++) {
    const pos = (h1 + i * h2) % f.m;
    if (!((f.bits[pos >> 3] >> (pos & 7)) & 1)) return false;
  }
  return true;
}

const f = parse(readFileSync("dist/rkn.bloom"));
console.log(`filter: m=${f.m} k=${f.k} n=${f.n} bytes=${f.bits.length}`);

const text = await (await fetch("https://antizapret.prostovpn.org/domains-export.txt")).text();
const all = text.split("\n").map((s) => s.trim()).filter((s) => s && s.includes("."));

// Sample known-blocked domains -> expect ~100% hits (proves hashing parity).
const SAMPLE = 2000;
const step = Math.max(1, Math.floor(all.length / SAMPLE));
let hits = 0,
  checked = 0;
for (let i = 0; i < all.length; i += step) {
  checked++;
  if (contains(f, all[i].toLowerCase())) hits++;
}
console.log(`known-blocked: ${hits}/${checked} hit (${((hits / checked) * 100).toFixed(2)}%)  <- must be 100%`);

// Random domains very unlikely to be listed -> measures false-positive rate.
let fp = 0;
const N = 5000;
for (let i = 0; i < N; i++) {
  const d = `nonexistent-${i}-${(i * 2654435761) >>> 0}.example-not-blocked-xyz.com`;
  if (contains(f, d)) fp++;
}
console.log(`random non-listed: ${fp}/${N} false positives (${((fp / N) * 100).toFixed(3)}%)  <- expect ~0.5%`);

// Parent-domain walk: a subdomain of a blocked domain should resolve via the parent.
function isBlocked(host) {
  const labels = host.split(".");
  for (let i = 0; i + 2 <= labels.length; i++) {
    if (contains(f, labels.slice(i).join("."))) return true;
  }
  return false;
}
const blocked = all[step * 3] || all[0];
console.log(`parent walk: "${blocked}" -> ${isBlocked(blocked)}; "cdn.${blocked}" -> ${isBlocked("cdn." + blocked)}  <- both true`);

if (hits / checked < 0.999) {
  console.error("PARITY FAILED: known-blocked hit rate < 99.9% — JS and Python hashing disagree.");
  process.exit(1);
}
console.log("PARITY OK");
