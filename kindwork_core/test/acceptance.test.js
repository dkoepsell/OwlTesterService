// Acceptance fixtures for the Kindwork module. The OwlTester port must pass the
// equivalent of every test here. Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { build, importModel, prepare, findings, check, load, InputError } from '../src/service.js';
import { reasonerAvailable } from '../src/reasoner.js';

const require = createRequire(import.meta.url);
const N3 = require('n3');
const fx = f => fs.readFileSync(new URL(`./fixtures/${f}`, import.meta.url), 'utf8');
const triples = ttl => new N3.Parser().parse(ttl).length;
const EM_DASH = /\u2014/;

test('A1 keyword source compiles with no errors and 14 record types', () => {
  const r = build(fx('job-site-tracker.kw'), { name: 'job-site-tracker.kw' });
  assert.equal(r.recordTypes.length, 14);
  assert.deepEqual(Object.keys(r.files).sort(), ['README.md', 'job-site-tracker-shapes.ttl', 'job-site-tracker.html', 'job-site-tracker.kindwork.json', 'job-site-tracker.kw', 'job-site-tracker.ttl']);
});

test('A2 compiler errors are line-numbered and plain', () => {
  const src = 'app "Bad"\nstatuss "License"\nhappening "Inspection"\n  held_by "Worker"\nthing "Worker"\nstatus "Permit"\n  issued_by "Worker"\n  bearer "Inspection"\n  held_by "Nobody"';
  try { build(src, { name: 'bad.kw' }); assert.fail('should not build'); }
  catch (e) {
    assert.ok(e instanceof InputError);
    const by = Object.fromEntries(e.diagnostics.map(d => [d.line, d.message]));
    assert.match(by[2], /isn't a keyword\. Did you mean status\?/);
    assert.match(by[4], /a happening can't have a holder\. held_by is for a status\./);
    assert.match(by[7], /issued_by needs an authority, but "Worker" is a thing \(line 5\)/);
    assert.match(by[8], /a status can't have a bearer\. bearer is for a quality, a tendency, a function, a role, or an authority\./);
    assert.match(by[9], /"Nobody" isn't defined in this file/);
    for (const d of e.diagnostics) { assert.doesNotMatch(d.message, /SubClassOf|owl:|BFO_|rdfs:/); assert.doesNotMatch(d.message, EM_DASH); }
  }
});

test('A3 keyword source, model and OWL round-trip without loss', () => {
  const fromModel = build(fx('job-site-tracker.kindwork.json'));
  const fromKw = build(fromModel.files['job-site-tracker.kw'], { name: 'x.kw' });
  assert.equal(fromKw.files['job-site-tracker.kw'].replace(/on \d{4}-\d\d-\d\d/, ''), fromModel.files['job-site-tracker.kw'].replace(/on \d{4}-\d\d-\d\d/, ''));
  assert.equal(triples(fromKw.files['job-site-tracker.ttl']), 190);
  assert.equal(triples(fromKw.files['job-site-tracker-shapes.ttl']), 216);
  const re = importModel(fromKw.files['job-site-tracker.ttl'], { name: 'job-site-tracker.ttl' });
  const kw = Object.fromEntries(re.model.terms.map(t => [t.name, t.keyword]));
  for (const t of fromModel.recordTypes) assert.equal(kw[t.name], t.keyword, t.name);
});

test('A4 the tracker is a standalone page carrying the schema and runtime', () => {
  const html = build(fx('job-site-tracker.kindwork.json')).files['job-site-tracker.html'];
  assert.match(html, /^<!doctype html>/);
  assert.match(html, /function KindworkRuntime\(root, schema, opts\)/);
  assert.match(html, /"name":"Electrical license"/);
  assert.doesNotMatch(html, /<\/script>[\s\S]*<\/script>[\s\S]*<\/script>/, 'exactly one inline script');
});

test('A5 interview conflicts become warnings with lines', () => {
  const r = load(fx('job-site-tracker.kw'), { name: 'job-site-tracker.kw' });
  const sev = r.warnings.map(w => w.severity).sort();
  assert.deepEqual(sev, ['chain', 'chain', 'partition']);
  assert.ok(r.warnings.every(w => Number.isInteger(w.line)));
});

test('A6 importing an ontology places classes by their BFO ancestors and flags straddles', () => {
  const r = importModel(fx('straddle.ttl'), { name: 'straddle.ttl' });
  const by = Object.fromEntries(r.model.terms.map(t => [t.name, t]));
  assert.equal(by['Manic episode'].imported.clash, 'partition');
  assert.equal(by['Severity score'].imported.clash, 'within');
  assert.equal(by['Mental disorder'].answers.c5, 'n');
  assert.equal(by['Clinic note'].keyword, null);
  assert.equal(by['Manic episode'].provenance.length, 1);
});

test('A7 findings are assembled from any reasoner result, three-valued', () => {
  const src = fx('straddle.ttl');
  const ok = findings(src, { name: 'straddle.ttl' }, { status: 'ok', consistent: true, unsatisfiable: [
    { iri: 'http://ex.org/x#Episode', label: 'Manic episode', partition: true, axioms: ['Manic episode SubClassOf process'] }] });
  assert.equal(ok.format, 'owltester-findings');
  assert.deepEqual(ok.verdict, { consistent: true, coherent: false });
  assert.equal(ok.findings[0].severity, 'partition');
  assert.equal(ok.findings.filter(f => f.id.startsWith('kw-kw') || f.title.includes('Filed')).length, 0, 'asserted straddles are suppressed when the reasoner ran');
  const late = findings(src, { name: 'straddle.ttl' }, { status: 'timeout', consistent: null, unsatisfiable: [], detail: 'The reasoner did not finish within 60 seconds.' });
  assert.deepEqual(late.verdict, { consistent: null, coherent: null });
  assert.equal(late.findings[0].verdict, 'undetermined');
  assert.ok(late.findings.some(f => f.severity === 'partition' && f.verdict === 'fail'), 'asserted straddles are reported when the reasoner did not run');
  for (const f of [...ok.findings, ...late.findings]) { assert.doesNotMatch(f.title + f.explanation, /SubClassOf|BFO_|owl:/); assert.doesNotMatch(f.title + f.explanation, EM_DASH); }
});

test('A8 prepare checks an ontology as given, and compiles anything else', () => {
  assert.equal(prepare(fx('straddle.ttl'), { name: 'straddle.ttl' }).ontology.text, fx('straddle.ttl'));
  assert.match(prepare(fx('job-site-tracker.kw'), { name: 'm.kw' }).ontology.text, /owl:imports <http:\/\/purl\.obolibrary\.org\/obo\/bfo\.owl>/);
});

test('A9 sidecar speaks JSON on stdin and stdout', () => {
  const run = req => spawnSync(process.execPath, [new URL('../bin/kindwork-core.mjs', import.meta.url).pathname], { input: JSON.stringify(req), encoding: 'utf8' });
  const ok = run({ op: 'lint', source: fx('job-site-tracker.kw'), name: 'm.kw' });
  assert.equal(ok.status, 0); assert.equal(JSON.parse(ok.stdout).warnings.length, 3);
  const bad = run({ op: 'build', source: 'statuss "X"', name: 'b.kw' });
  assert.equal(bad.status, 2); assert.equal(JSON.parse(bad.stdout).errors[0].line, 1);
});

test('A10 generated text never contains an em-dash', () => {
  const r = build(fx('job-site-tracker.kindwork.json'));
  for (const [name, text] of Object.entries(r.files)) assert.doesNotMatch(text, EM_DASH, name);
});

test('A11 reference reasoner run: HermiT finds both straddles', { skip: !reasonerAvailable() && 'ROBOT not installed' }, async () => {
  const f = await check(fx('straddle-imports-bfo.ttl'), { name: 'straddle.ttl' });
  assert.deepEqual(f.verdict, { consistent: true, coherent: false });
  const sev = f.findings.filter(x => x.check === 'coherence').map(x => x.severity).sort();
  assert.deepEqual(sev, ['partition', 'within']);
  assert.ok(f.findings.every(x => x.axioms.every(a => !/\]\(/.test(a))), 'axioms are de-linked');
});
