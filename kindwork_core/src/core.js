// Runs the Kindwork page's own generators server-side, so the service and the
// artifact can never disagree. The page is vendored at core/kindwork.html; its
// inline scripts are compiled once and executed in a fresh, isolated context per
// call. The page exposes its functions through window.__KINDWORK_EXPORT__.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const N3 = require('n3');
const { DOMParser } = require('@xmldom/xmldom');

const here = path.dirname(fileURLToPath(import.meta.url));
export const CORE_PATH = process.env.KINDWORK_CORE || path.join(here, '..', 'core', 'kindwork.html');

const html = fs.readFileSync(CORE_PATH, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length !== 2) throw new Error(`Expected 2 inline scripts in ${CORE_PATH}, found ${scripts.length}`);
if (!scripts[1].includes('__KINDWORK_EXPORT__')) throw new Error(`${CORE_PATH} has no __KINDWORK_EXPORT__ hook`);
const cssMatch = /<style id="runtime-css">([\s\S]*?)<\/style>/.exec(html);
if (!cssMatch) throw new Error(`${CORE_PATH} has no runtime-css block`);
const RUNTIME_CSS = cssMatch[1];
const compiled = new vm.Script(scripts[0] + '\n;\n' + scripts[1], { filename: 'kindwork-core.js' });
const versionMatch = /Kindwork|kindwork/.test(html);
export const CORE_INFO = { path: CORE_PATH, bytes: Buffer.byteLength(html), ok: versionMatch };

function stubElement() {
  return {
    innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    addEventListener() {}, removeEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {} }, appendChild() {}, remove() {}, focus() {}, scrollIntoView() {}
  };
}

// Returns a fresh Kindwork API with its own model state.
export function createCore() {
  let api = null;
  const els = {};
  const document = {
    getElementById: id => id === 'runtime-css' ? { textContent: RUNTIME_CSS } : (els[id] ||= stubElement()),
    addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    createElement: () => stubElement(), createRange: () => ({ selectNodeContents() {} }), body: stubElement()
  };
  const window = { N3, scrollTo() {}, __KINDWORK_EXPORT__: x => { api = x; } };
  const ctx = vm.createContext({
    window, document, N3, DOMParser, URL, console,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    navigator: {}, getSelection: () => null, setTimeout, clearTimeout
  });
  compiled.runInContext(ctx, { timeout: 5000 });
  if (!api) throw new Error('Kindwork core did not export its functions');
  // Start from an empty model, not the page's built-in example.
  Object.assign(api.S, { task: '', appName: 'Tracker', terms: [], rels: [], findings: [], findingsMeta: null, ns: '' });
  return api;
}
