// Static checks of the PWA in mobile/ (SPEC §16.2): offline cache complete, no external
// resources, strict CSP, matching versions.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../mobile/", import.meta.url));
const read = (f) => readFileSync(join(ROOT, f), "utf-8");
const walk = (dir) => readdirSync(dir).flatMap((n) => (statSync(join(dir, n)).isDirectory() ? walk(join(dir, n)) : [join(dir, n)]));
const files = walk(ROOT).map((f) => relative(ROOT, f).replace(/\\/g, "/"));

test("the service worker caches every file of the site", () => {
  const sw = read("sw.js");
  const listed = JSON.parse(sw.match(/const FILES = (\[[\s\S]*?\]);/)[1].replace(/,\s*\]/, "]"));
  const expected = files.filter((f) => f !== "sw.js").sort();
  assert.deepEqual(listed.filter((f) => f !== "./").sort(), expected);
});

test("app and service worker versions match", () => {
  const sw = /const VERSION = "([^"]+)"/.exec(read("sw.js"))[1];
  const app = /APP_VERSION = "([^"]+)"/.exec(read("js/app.js"))[1];
  assert.equal(sw, app);
});

test("no external resources or network APIs", () => {
  for (const f of files.filter((x) => /\.(html|js|css|webmanifest)$/.test(x))) {
    const text = read(f);
    assert.doesNotMatch(text, /(src|href)=["']?(https?:)?\/\//i, f);
    assert.doesNotMatch(text, /url\(\s*["']?(https?:)?\/\//i, f);
    assert.doesNotMatch(text, /\b(XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b/, f);
    if (f !== "sw.js") assert.doesNotMatch(text, /\bfetch\(/, f);
  }
});

test("strict CSP and no inline scripts or styles", () => {
  const html = read("index.html");
  const csp = /http-equiv="Content-Security-Policy" content="([^"]+)"/.exec(html)[1];
  assert.match(csp, /default-src 'self'/);
  assert.match(csp, /connect-src 'self'/);
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|https?:/);
  assert.doesNotMatch(html, /<script>(?!<\/script>)|<script(?![^>]*\ssrc=)[^>]*>/);
  assert.doesNotMatch(html, /\sstyle=/);
  for (const f of files.filter((x) => x.endsWith(".js"))) assert.doesNotMatch(read(f), /\sstyle="/, f);
});

test("manifest is installable", () => {
  const m = JSON.parse(read("manifest.webmanifest"));
  assert.equal(m.display, "standalone");
  assert.equal(m.start_url, "./");
  const sizes = m.icons.map((i) => i.sizes);
  assert.ok(sizes.includes("192x192") && sizes.includes("512x512"));
  for (const i of m.icons) assert.ok(files.includes(i.src), i.src);
});
