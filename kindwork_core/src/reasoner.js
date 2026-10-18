// HermiT through ROBOT. Every run merges the ontology with BFO 2020 core (via a
// catalog, so owl:imports never touches the network) and a one-axiom IAO bridge.
// Outcomes are three-valued: a run that does not finish is undetermined, never a pass.
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const VENDOR = process.env.KINDWORK_VENDOR || path.join(here, '..', 'vendor');
const ROBOT_JAR = process.env.ROBOT_JAR || path.join(VENDOR, 'robot.jar');
const JAVA = process.env.JAVA_BIN || 'java';
const TIMEOUT_MS = Number(process.env.REASONER_TIMEOUT_MS || 60000);
const MAX_PARALLEL = Number(process.env.REASONER_MAX_PARALLEL || 2);

export const REASONER = { name: 'HermiT', via: 'ROBOT 1.9.6', profile: 'OWL 2 DL' };
export function reasonerAvailable() { return existsSync(ROBOT_JAR) && existsSync(path.join(VENDOR, 'bfo-core.owl')); }

let running = 0; const waiting = [];
async function slot() { if (running < MAX_PARALLEL) { running++; return; } await new Promise(r => waiting.push(r)); running++; }
function release() { running--; const next = waiting.shift(); if (next) next(); }

function runRobot(args, cwd) {
  return new Promise(resolve => {
    const child = spawn(JAVA, ['-Xmx2g', '-jar', ROBOT_JAR, '--catalog', path.join(VENDOR, 'catalog-v001.xml'), ...args], { cwd });
    let out = '', timedOut = false;
    child.stdout.on('data', d => { out += d; }); child.stderr.on('data', d => { out += d; });
    const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL'); }, TIMEOUT_MS);
    child.on('error', e => { clearTimeout(timer); resolve({ code: -1, out: String(e), timedOut: false, spawnError: true }); });
    child.on('close', code => { clearTimeout(timer); resolve({ code, out, timedOut }); });
  });
}

const stripLinks = s => s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\s+\[x\]\s*$/, '').trim();

// Parse ROBOT's Markdown explanation into { iri -> { label, axioms[], partition } }.
function parseExplanation(md) {
  const out = new Map(); let cur = null;
  for (const line of md.split('\n')) {
    const h = /^##\s+\[([^\]]*)\]\(([^)]+)\)\s+SubClassOf\s+\[Nothing\]/.exec(line);
    if (h) { cur = { label: h[1], axioms: [], partition: false }; out.set(h[2], cur); continue; }
    if (/^#\s/.test(line)) { cur = null; continue; }
    if (cur && /^\s*-\s+/.test(line)) {
      const ax = stripLinks(line.replace(/^\s*-\s+/, ''));
      if (ax && !cur.axioms.includes(ax)) cur.axioms.push(ax);
      if (/BFO_0000002\)? DisjointWith .*BFO_0000003|BFO_0000003\)? DisjointWith .*BFO_0000002/.test(line)) cur.partition = true;
    }
  }
  return out;
}

// Returns { status: 'ok'|'timeout'|'error'|'unavailable', consistent, unsatisfiable: [{iri,label,axioms,partition}], detail }
export async function reason(ontologyText, ext = 'ttl') {
  if (!reasonerAvailable()) return { status: 'unavailable', consistent: null, unsatisfiable: [], detail: 'No reasoner is installed on this build service.' };
  await slot();
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'kindwork-'));
  try {
    const input = path.join(dir, 'input.' + ext);
    await fs.writeFile(input, ontologyText);
    const bridge = path.join(VENDOR, 'iao-bridge.ttl');
    const r = await runRobot(['merge', '--input', input, '--input', bridge, 'reason', '--reasoner', 'HermiT'], dir);
    if (r.timedOut) return { status: 'timeout', consistent: null, unsatisfiable: [], detail: `The reasoner did not finish within ${Math.round(TIMEOUT_MS / 1000)} seconds.` };
    if (r.spawnError) return { status: 'unavailable', consistent: null, unsatisfiable: [], detail: 'Java could not be started on this build service.' };
    if (/inconsistent/i.test(r.out) && !/unsatisfiable:/.test(r.out)) {
      const ex = await runRobot(['merge', '--input', input, '--input', bridge, 'explain', '--reasoner', 'HermiT', '--mode', 'inconsistency', '--explanation', path.join(dir, 'x.md')], dir);
      let axioms = [];
      try { axioms = (await fs.readFile(path.join(dir, 'x.md'), 'utf8')).split('\n').filter(l => /^\s*-\s+/.test(l)).map(l => stripLinks(l.replace(/^\s*-\s+/, ''))).filter(Boolean).slice(0, 20); } catch (e) {}
      return { status: ex.timedOut ? 'timeout' : 'ok', consistent: false, unsatisfiable: [], axioms, detail: '' };
    }
    const iris = [...r.out.matchAll(/unsatisfiable:\s+(\S+)/g)].map(m => m[1]);
    if (r.code !== 0 && !iris.length) {
      const reason = (r.out.split('\n').find(l => /ERROR|Exception/.test(l)) || 'ROBOT could not load the ontology.').replace(/^.*?(ERROR|Exception)\S*\s*/, '').slice(0, 300);
      return { status: 'error', consistent: null, unsatisfiable: [], detail: reason };
    }
    if (!iris.length) return { status: 'ok', consistent: true, unsatisfiable: [], detail: '' };
    const ex = await runRobot(['merge', '--input', input, '--input', bridge, 'explain', '--reasoner', 'HermiT', '--mode', 'unsatisfiability', '--unsatisfiable', 'all', '--explanation', path.join(dir, 'x.md')], dir);
    let parsed = new Map();
    if (!ex.timedOut) { try { parsed = parseExplanation(await fs.readFile(path.join(dir, 'x.md'), 'utf8')); } catch (e) {} }
    return {
      status: 'ok', consistent: true, detail: ex.timedOut ? 'Explanations timed out; the classes are listed without them.' : '',
      unsatisfiable: iris.map(iri => ({ iri, ...(parsed.get(iri) || { label: '', axioms: [], partition: null }) }))
    };
  } finally {
    release();
    fs.rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}
