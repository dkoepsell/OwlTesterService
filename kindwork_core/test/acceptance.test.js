// Acceptance fixtures for the Kindwork module. The OwlTester port must pass the
// equivalent of every test here. Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { build, importModel, prepare, findings, check, load, InputError } from '../src/service.js';
import { ingest } from '../src/ingest.js';
import { propose, buildPrompt } from '../src/llm.js';
import { createCore } from '../src/core.js';
import { reasonerAvailable } from '../src/reasoner.js';

const require = createRequire(import.meta.url);
const N3 = require('n3');
const fx = f => fs.readFileSync(new URL(`./fixtures/${f}`, import.meta.url), 'utf8');
const J = x => JSON.parse(JSON.stringify(x)); // values from the vm realm
const triples = ttl => new N3.Parser().parse(ttl).length;
const EM_DASH = /\u2014/;

test('A1 keyword source compiles; the gate holds back the one term with a crossing conflict', () => {
  const r = build(fx('job-site-tracker.kw'), { name: 'job-site-tracker.kw' });
  assert.equal(r.recordTypes.length, 13);
  assert.deepEqual(r.heldBack, ['Contract period']);
  assert.deepEqual(r.proposed, []);
  assert.deepEqual(Object.keys(r.files).sort(), ['README.md', 'job-site-tracker-shapes.ttl', 'job-site-tracker.html', 'job-site-tracker.kindwork.json', 'job-site-tracker.kw', 'job-site-tracker.ttl']);
  assert.match(r.files['job-site-tracker.kw'], /contract period[\s\S]*# held back from the build/i);
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
  assert.equal(triples(fromKw.files['job-site-tracker.ttl']), 177);
  assert.equal(triples(fromKw.files['job-site-tracker-shapes.ttl']), 188);
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

const fxi = f => fs.readFileSync(new URL(`./fixtures/ingest/${f}`, import.meta.url));

test('A12 the source view holds the whole model: undecided and proposed terms round-trip', () => {
  const core = createCore();
  const src = 'app "Claims"\n\nhappening "Claim"\n  proposed\n  signal held\n\nrole "Adjuster"\n\nundecided "Denial"\n  means "When a claim is refused."\n';
  const r = core.parseKw(src);
  assert.deepEqual(J(r.errors), []);
  core.applyManifest(r.model);
  assert.equal(core.S.terms.find(t => t.name === 'Claim').state, 'proposed');
  assert.equal(core.kwOf(core.S.terms.find(t => t.name === 'Denial')), null);
  const again = core.genKW(core.genSchema());
  assert.match(again, /happening "Claim"\n  proposed\n  signal held/);
  assert.match(again, /undecided "Denial"\n  means "When a claim is refused\."/);
  const bad = core.parseKw('undecided "Denial"\n  about "Claim"\nhappening "Claim"');
  assert.match(bad.errors[0].message, /still undecided, so it can't have links yet/);
});

test('A13 resolving the conflict releases the held-back term', () => {
  const fixed = fx('job-site-tracker.kw').replace(/(period "Contract period"[\s\S]*?)  signal extended\n/, '$1');
  const r = build(fixed, { name: 'm.kw' });
  assert.equal(r.recordTypes.length, 14);
  assert.deepEqual(r.heldBack, []);
});

test('A14 term lists: lines, meanings, tabs, CSV with header and quotes, bullets, duplicates', () => {
  const core = createCore();
  const plain = core.parseTermList('Claim: a request for payment\n- Policyholder\n2. Denial\nClaim\n', false);
  assert.deepEqual(J(plain.map(t => t.name)), ['Claim', 'Policyholder', 'Denial']);
  assert.equal(plain[0].desc, 'a request for payment');
  const csv = core.parseTermList(fxi('claims-terms.csv').toString(), true);
  assert.deepEqual(J(csv.map(t => t.name)), ['Claim', 'Policyholder', 'Prior authorization', 'Denial', 'Adjuster']);
  assert.equal(csv[0].desc, 'A request for payment under a policy, submitted by a provider');
  const tab = core.parseTermList('Name\tMeaning\nClaim\tA request\nDenial\t', false);
  assert.deepEqual(J(tab.map(t => [t.name, t.desc])), [['Claim', 'A request'], ['Denial', '']]);
});

test('A15 proposals only fill proposed terms, ignore invented ones, and never confirm', () => {
  const core = createCore();
  core.addTermsFromList(core.parseTermList(fxi('claims-terms.csv').toString(), true), 'proposed');
  const n = core.applyProposals(JSON.parse(fxi('mock-proposal.json').toString()));
  assert.equal(n, 5);
  assert.ok(core.S.terms.every(t => t.state === 'proposed'));
  assert.ok(!core.S.terms.some(t => t.name === 'Invented term'));
  assert.equal(core.kwOf(core.S.terms.find(t => t.name === 'Prior authorization')), 'status');
  assert.equal(core.genSchema().collections.length, 0, 'nothing is built until a person confirms');
  const claim = core.S.terms.find(t => t.name === 'Claim');
  assert.ok(core.findConflicts().some(c => c.tid === claim.id && c.type === 'held'), 'held vs happening card raised for Claim');
});

test('A16 ingest: CSV, XLSX data dictionary, JSON Schema, SQL DDL', async () => {
  const csv = await ingest('terms.csv', fxi('claims-terms.csv'));
  assert.equal(csv.terms.length, 5);
  const xlsx = await ingest('dd.xlsx', fxi('data-dictionary.xlsx'));
  assert.deepEqual(xlsx.terms.map(t => t.name), ['Claim status', 'Coverage effective date', 'Network provider']);
  assert.equal(xlsx.terms[0].desc, 'Where the claim is in adjudication');
  assert.equal(xlsx.terms[0].hints, 'type: varchar');
  const js = await ingest('claim.schema.json', fxi('claims-schema.json'));
  const names = js.terms.map(t => t.name);
  for (const n of ['Claim', 'Member', 'Claim status', 'Service date']) assert.ok(names.includes(n), n);
  assert.match(js.terms.find(t => t.name === 'Claim status').hints, /values: submitted, pended, paid, denied/);
  assert.match(js.context, /regional health plan/);
  const sql = await ingest('claims.sql', fxi('claims.sql'));
  const claim = sql.terms.find(t => t.name === 'Claim');
  assert.equal(claim.desc, 'A request for payment under a policy.');
  assert.match(claim.hints, /member_id links to Members/);
  assert.ok(sql.terms.some(t => t.name === 'Claim status') && sql.terms.some(t => t.name === 'Claim submitted'));
  await assert.rejects(ingest('x.pdf', Buffer.from('x')), /Send a \.csv/);
});

test('A17 propose builds the prompt from the page and filters to the terms asked about', async () => {
  const prompt = buildPrompt({ kind: 'terms', terms: [{ name: 'Claim', desc: 'A request' }], context: 'Health plan claims' });
  assert.match(prompt, /- Claim: A request/);
  assert.match(prompt, /do not add, merge, split, or rename terms/);
  assert.match(prompt, /Health plan claims/);
  await assert.rejects(async () => buildPrompt({ kind: 'task', task: 'short' }), /few sentences/);
  process.env.KINDWORK_LLM_MOCK = new URL('./fixtures/ingest/mock-proposal.json', import.meta.url).pathname;
  try {
    const r = await propose({ kind: 'terms', terms: ['Claim', 'Policyholder', 'Prior authorization', 'Denial', 'Adjuster'].map(name => ({ name })) });
    assert.equal(r.model, 'mock');
    assert.equal(r.result.terms.length, 5, 'the invented term is dropped server-side');
  } finally { delete process.env.KINDWORK_LLM_MOCK; }
});

test('A18 the source view refuses silent removal', () => {
  const core = createCore();
  core.applyManifest(JSON.parse(fx('job-site-tracker.kindwork.json')));
  const src = core.genKW(core.genSchema()).replace(/thing "Worker"[\s\S]*?\n\n/, '');
  const first = core.applySource(src.replace(/ +at "Job site"\n|participant "Worker"\n|held_by "Worker"\n|bearer "Worker"\n/g, ''), false);
  assert.deepEqual(J(first.removed), ['Worker']);
  assert.equal(core.S.terms.length, 14, 'nothing changed');
});

test('A19 sidecar: ingest and propose', () => {
  const run = (req, env) => spawnSync(process.execPath, [new URL('../bin/kindwork-core.mjs', import.meta.url).pathname], { input: JSON.stringify(req), encoding: 'utf8', env: { ...process.env, ...env } });
  const ing = run({ op: 'ingest', name: 'claims.sql', base64: fxi('claims.sql').toString('base64') });
  assert.equal(ing.status, 0); assert.ok(JSON.parse(ing.stdout).terms.length >= 2);
  const nokey = run({ op: 'propose', kind: 'terms', terms: [{ name: 'Claim' }] }, { KINDWORK_LLM_KEY: '', ANTHROPIC_API_KEY: '', SOOL_ANTHROPIC_KEY: '' });
  assert.equal(nokey.status, 3); assert.equal(JSON.parse(nokey.stdout).code, 'sampling_disabled');
  const mock = run({ op: 'propose', kind: 'terms', terms: [{ name: 'Claim' }, { name: 'Denial' }] }, { KINDWORK_LLM_MOCK: new URL('./fixtures/ingest/mock-proposal.json', import.meta.url).pathname });
  assert.equal(mock.status, 0); assert.deepEqual(JSON.parse(mock.stdout).result.terms.map(t => t.name), ['Claim', 'Denial']);
});

const SHOP = `app "Shop"
thing "Car"
thing "Wheel"
  part_of "Car"
place "Building"
place "Room"
  part_of "Building"
happening "Inspection"
  participant "Car"
  results_in "Inspection report"
  precedes "Repair"
happening "Inspection step"
  part_of "Inspection"
happening "Repair"
record "Inspection report"
  about "Car"
  kept_on "Paper form"
thing "Paper form"
`;

test('A20 structural connections compile to BFO relations, each side of the divide', () => {
  const r = build(SHOP, { name: 'shop.kw' });
  const ttl = r.files['shop.ttl'];
  const restr = (cls, prop, target) => new RegExp(`:${cls} a owl:Class[^.]*owl:onProperty ${prop} ; owl:someValuesFrom :${target} \\]`).test(ttl);
  assert.ok(restr('Wheel', 'obo:BFO_0000176', 'Car'), 'continuant part of');
  assert.ok(restr('Room', 'obo:BFO_0000176', 'Building'));
  assert.ok(restr('InspectionStep', 'obo:BFO_0000132', 'Inspection'), 'occurrent part of');
  assert.ok(restr('Inspection', 'obo:BFO_0000063', 'Repair'), 'precedes');
  assert.ok(restr('Inspection', 'obo:RO_0002234', 'InspectionReport'), 'has output');
  assert.ok(restr('InspectionReport', 'obo:BFO_0000084', 'PaperForm'), 'generically depends on');
  // Round trip: keyword source, then Turtle back to the same connections.
  const again = build(r.files['shop.kw'], { name: 'x.kw' });
  assert.equal(again.files['shop.kw'].replace(/on \d{4}-\d\d-\d\d/, ''), r.files['shop.kw'].replace(/on \d{4}-\d\d-\d\d/, ''));
  const re = importModel(ttl, { name: 'shop.ttl' });
  const id = Object.fromEntries(re.model.terms.map(t => [t.id, t.name]));
  const got = re.model.relations.filter(x => x.rel !== 'isA').map(x => `${id[x.from]} ${x.rel} ${id[x.to]}`).sort();
  for (const want of ['Wheel partOf Car', 'Inspection step partOf Inspection', 'Inspection precedes Repair', 'Inspection resultsIn Inspection report', 'Inspection report keptOn Paper form']) assert.ok(got.includes(want), want);
  // The tracker gets the connections as fields and says them as rules.
  assert.match(r.files['shop.html'], /Every Wheel is part of some Car\./);
});

test('A21 connections the kinds cannot have are refused in plain words', () => {
  try { build('thing "Car"\nhappening "Drive"\nthing "Wheel"\n  part_of "Drive"\nhappening "Stop"\n  precedes "Car"', { name: 'x.kw' }); assert.fail('should not build'); }
  catch (e) {
    const by = Object.fromEntries(e.diagnostics.map(d => [d.line, d.message]));
    assert.match(by[4], /part_of needs a thing, but "Drive" is a happening/);
    assert.match(by[6], /precedes needs a happening, but "Car" is a thing/);
    for (const d of e.diagnostics) { assert.doesNotMatch(d.message, /BFO_|owl:/); assert.doesNotMatch(d.message, EM_DASH); }
  }
});

test('A22 suggested connections: prompt from the slot table, replies filtered to what the interview allows', async () => {
  const core = createCore();
  const p = buildPrompt({ kind: 'relations', terms: [{ name: 'Car', kind: 'thing' }, { name: 'Wheel', kind: 'thing' }] });
  assert.match(p, /partOf \(happening -> happening; record -> record; thing -> thing; group -> group; place -> place; period -> period\)/);
  assert.match(p, /every member of the first term/);
  assert.throws(() => buildPrompt({ kind: 'relations', terms: [{ name: 'Car', kind: 'thing' }] }), InputError);
  const terms = [{ name: 'Car', kind: 'thing' }, { name: 'Wheel', kind: 'thing' }, { name: 'Inspection', kind: 'happening' }, { name: 'Inspection report', kind: 'record' }];
  process.env.KINDWORK_LLM_MOCK = new URL('./fixtures/ingest/mock-relations.json', import.meta.url).pathname;
  try {
    const { result } = await propose({ kind: 'relations', terms });
    assert.deepEqual(result.relations.map(r => `${r.from} ${r.rel} ${r.to}`), ['Wheel partOf Car', 'Inspection resultsIn Inspection report', 'Inspection participant Car']);
  } finally { delete process.env.KINDWORK_LLM_MOCK; }
  assert.equal(core.sentence('Electrical license', 'heldBy', 'Worker', 'status'), 'Every Electrical license is held by some Worker.');
  assert.equal(core.sentence('Inspection step', 'partOf', 'Inspection', 'happening'), 'Every Inspection step is a step in some Inspection.');
  assert.equal(core.sentence('Inspection', 'participant', 'Car', 'happening'), 'Every Inspection has some Car taking part.');
});
