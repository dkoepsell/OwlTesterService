// The three operations, shared by the REST API, the MCP server and the CLI.
import { createRequire } from 'node:module';
import { createCore } from './core.js';
import { parseKw } from './kw.js';
import { reason, reasonerAvailable, REASONER } from './reasoner.js';

const require = createRequire(import.meta.url);
const JSZip = require('jszip');

export class InputError extends Error {
  constructor(message, diagnostics) { super(message); this.status = 422; this.diagnostics = diagnostics || []; }
}

const plain = html => String(html).replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');

export function detect(source, hint = '') {
  const h = String(hint).toLowerCase(), head = String(source).trimStart().slice(0, 4000);
  if (/\.kw$/.test(h) || h === 'kw') return 'kw';
  if (head.startsWith('{')) return 'json';
  if (head.startsWith('<')) return 'rdfxml';
  if (/^\s*(Prefix|Ontology)\s*\(/m.test(head)) return 'functional';
  const firstCode = head.split('\n').map(l => l.trim()).find(l => l && !l.startsWith('#')) || '';
  if (/^(app|namespace|thing|group|place|quality|tendency|function|role|authority|record|code|status|obligation|happening|moment|period)\s+"/.test(firstCode)) return 'kw';
  return 'turtle';
}

// Loads any accepted input into a fresh core. Throws InputError with diagnostics.
export function load(source, { name = 'model', format } = {}) {
  if (typeof source !== 'string' || !source.trim()) throw new InputError('Send the model, keyword source, or ontology as text.');
  if (source.length > 8 * 1024 * 1024) throw new InputError('That input is over 8 MB. Split it, or check it in OwlTester directly.');
  const kind = format || detect(source, name);
  const core = createCore();
  const out = { core, kind, warnings: [], ontology: null };
  if (kind === 'functional') throw new InputError('This looks like OWL functional syntax. Send Turtle or RDF/XML.');
  if (kind === 'json') {
    let j; try { j = JSON.parse(source); } catch (e) { throw new InputError("That JSON doesn't parse."); }
    if (j.format !== 'kindwork-model') throw new InputError('JSON input must be a kindwork-model file.');
    try { core.applyManifest(j); } catch (e) { throw new InputError(e.message); }
  } else if (kind === 'kw') {
    const r = parseKw(source, core.SLOTS);
    if (r.errors.length) throw new InputError(`The keyword source has ${r.errors.length} error${r.errors.length > 1 ? 's' : ''}.`, r.errors);
    core.applyManifest(r.model);
    const lineByName = new Map(r.model.terms.map(t => [t.name.toLowerCase(), r.lineOf.get(t.id)]));
    out.lineOf = name => lineByName.get(String(name).toLowerCase()) || null;
  } else {
    let triples;
    try { triples = kind === 'rdfxml' ? core.parseRdfXml(source) : core.parseTurtle(source); }
    catch (e) { throw new InputError(e && e.message ? e.message : 'The ontology could not be read.'); }
    let res; try { res = core.importTriples(triples); } catch (e) { throw new InputError(e.message); }
    core.applyImport(res, 'replace', name);
    out.ontology = { text: source, ext: kind === 'rdfxml' ? 'owl' : 'ttl', classes: res.total, imported: res.terms.length };
  }
  for (const c of core.findConflicts()) {
    const t = core.termById(c.tid);
    out.warnings.push({ line: out.lineOf ? out.lineOf(t.name) : null, term: t.name, severity: c.sev, message: `${c.title} ${plain(c.body)}` });
  }
  return out;
}

function summary(core, sch) {
  return {
    app: sch.app, slug: sch.slug, namespace: core.nsBase(),
    recordTypes: sch.collections.map(c => ({ name: c.name, keyword: c.kw, bfo: core.KW[c.kw].iri })),
    unplaced: core.S.terms.filter(t => !core.kwOf(t)).map(t => t.name)
  };
}

export function build(source, opts = {}) {
  const { core, warnings, kind } = load(source, opts);
  const sch = core.genSchema();
  if (!sch.collections.length) throw new InputError('Nothing to build: no term has a keyword yet.');
  const s = sch.slug;
  const files = {
    [`${s}.html`]: core.genTracker(sch),
    [`${s}.ttl`]: core.genOWL(sch),
    [`${s}-shapes.ttl`]: core.genSHACL(sch),
    [`${s}.kw`]: core.genKW(sch),
    [`${s}.kindwork.json`]: core.genManifest(sch),
    'README.md': core.genReadme(sch) + core.genReadmeTail(sch)
  };
  return { ok: true, input: kind, ...summary(core, sch), warnings, files };
}

export async function buildZip(result) {
  const zip = new JSZip(), dir = zip.folder(result.slug);
  for (const [name, text] of Object.entries(result.files)) dir.file(name, text);
  return zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
}

export function importModel(source, opts = {}) {
  const { core, warnings, kind, ontology } = load(source, opts);
  const sch = core.genSchema();
  return { ok: true, input: kind, ...summary(core, sch), ontology: ontology ? { classes: ontology.classes, imported: ontology.imported } : null, warnings, model: JSON.parse(core.genManifest(sch)) };
}

// Step 1 of a check: the ontology the reasoner should run on. An ontology input is
// checked as given (all classes); a model or keyword source is compiled first.
export function prepare(source, opts = {}) {
  const { core, kind, ontology } = load(source, opts);
  return { input: kind, ontology: ontology ? { text: ontology.text, ext: ontology.ext } : { text: core.genOWL(core.genSchema()), ext: 'ttl' } };
}

// Reference check: prepare, reason with the bundled ROBOT runner, assemble findings.
// Inside OwlTester, step 2 is OwlTester's own reasoner pipeline instead.
export async function check(source, opts = {}) {
  const p = prepare(source, opts);
  return findings(source, opts, await reason(p.ontology.text, p.ontology.ext));
}

// Step 3: turn a reasoner result into an owltester-findings object.
// r = { status: 'ok'|'timeout'|'error'|'unavailable', consistent, unsatisfiable: [{iri,label,axioms,partition}], axioms?, detail }
export function findings(source, opts, r) {
  const { core, kind } = load(source, opts);
  const findings = [];
  const termByIri = new Map(core.S.terms.map(t => [core.iriOf(t), t]));

  if (r.status !== 'ok') {
    findings.push({ id: 'reasoner', check: 'consistency', severity: 'info', verdict: 'undetermined', classes: [],
      title: 'The reasoner did not reach a verdict', explanation: `${r.detail} Consistency and coherence are undetermined, not passed.`, axioms: [] });
  } else if (r.consistent === false) {
    findings.push({ id: 'inconsistent', check: 'consistency', severity: 'info', verdict: 'fail', classes: [],
      title: 'The ontology contradicts itself',
      explanation: 'No situation can satisfy every statement in it at once, so a reasoner can conclude anything from it. The assertions below are one minimal set that conflicts.',
      axioms: r.axioms || [] });
  } else {
    r.unsatisfiable.forEach((u, i) => {
      const t = termByIri.get(u.iri);
      const label = (t && t.name) || u.label || u.iri.replace(/^.*[#\/]/, '');
      const anchors = t && t.imp && t.imp.anchors.length > 1 ? ` (${t.imp.anchors.join(' and ')})` : '';
      const partition = u.partition === true;
      findings.push({
        id: `unsat-${i + 1}`, check: 'coherence', severity: partition ? 'partition' : 'within', verdict: 'fail', classes: [u.iri],
        title: partition ? `${label} is filed as something that happens and something that persists` : `${label} is filed under two kinds that exclude each other`,
        explanation: partition
          ? `BFO makes those two disjoint${anchors}, so nothing can be a ${label}, and every conclusion that involves it is unsound. Decide which it is, or split it into two terms.`
          : `BFO keeps those kinds apart${anchors}, so nothing can be a ${label}. Decide which it is, or split it into the feature and the record of it.`,
        axioms: u.axioms || []
      });
    });
    if (r.detail) findings.push({ id: 'explain', check: 'coherence', severity: 'info', verdict: 'undetermined', classes: [], title: 'Some explanations are missing', explanation: r.detail, axioms: [] });
  }

  for (const c of core.findConflicts()) {
    if (c.type === 'imp' && r.status === 'ok') continue; // the reasoner is authoritative on asserted straddles
    const t = core.termById(c.tid), chain = ['auth', 'scope', 'corr'].includes(c.type);
    findings.push({
      id: `kw-${c.id}`, check: chain ? 'chain' : 'coherence', severity: c.sev, verdict: 'fail', classes: [core.iriOf(t)],
      title: `${t.name}: ${c.title}`,
      explanation: plain(c.body) + (c.type === 'imp' ? ' Found in the asserted hierarchy; the reasoner did not run.' : chain ? '' : ' From the interview answers.'),
      axioms: []
    });
  }

  return {
    format: 'owltester-findings', version: '0.1', generator: 'kindwork-build', generated: new Date().toISOString(),
    ontology: core.nsBase(), input: kind,
    reasoner: r.status === 'unavailable' ? null : { name: REASONER.name, version: REASONER.via, profile: REASONER.profile },
    verdict: { consistent: r.status === 'ok' ? r.consistent : null, coherent: r.status === 'ok' && r.consistent ? r.unsatisfiable.length === 0 : null },
    findings
  };
}

export function health() {
  let core = 'ok';
  try { createCore(); } catch (e) { core = e.message; }
  return { ok: core === 'ok', core, reasoner: reasonerAvailable() ? REASONER : null };
}
