#!/usr/bin/env node
// Sidecar entry point. OwlTester calls this with one JSON request on stdin and
// reads one JSON response on stdout. Exit 0 on success, 2 on input errors, 1 otherwise.
//
//   {"op":"build",    "source":"...", "name":"model.kw"}
//   {"op":"import",   "source":"...", "name":"client.owl"}
//   {"op":"lint",     "source":"...", "name":"model.kw"}
//   {"op":"prepare",  "source":"...", "name":"model.kw"}
//   {"op":"findings", "source":"...", "name":"model.kw", "reasoner": { status, consistent, unsatisfiable: [...] }}
//   {"op":"health"}
import { build, importModel, prepare, findings, load, health, InputError } from '../src/service.js';

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { raw += d; });
process.stdin.on('end', () => {
  let req;
  try { req = JSON.parse(raw); } catch (e) { return done(1, { ok: false, error: 'The request was not JSON.' }); }
  const opts = { name: req.name || 'model', format: req.format };
  try {
    switch (req.op) {
      case 'health': return done(0, health());
      case 'build': return done(0, build(req.source, opts));
      case 'import': return done(0, importModel(req.source, opts));
      case 'prepare': return done(0, { ok: true, ...prepare(req.source, opts) });
      case 'lint': { const r = load(req.source, opts); return done(0, { ok: true, input: r.kind, errors: [], warnings: r.warnings }); }
      case 'findings':
        if (!req.reasoner || typeof req.reasoner.status !== 'string') return done(2, { ok: false, error: 'findings needs a reasoner result with a status.' });
        return done(0, findings(req.source, opts, req.reasoner));
      default: return done(2, { ok: false, error: `Unknown op "${req.op}".` });
    }
  } catch (e) {
    if (e instanceof InputError) return done(2, { ok: false, error: e.message, errors: e.diagnostics });
    return done(1, { ok: false, error: 'Internal error in kindwork-core.', detail: String(e && e.message || e) });
  }
});
function done(code, body) { process.stdout.write(JSON.stringify(body)); process.exitCode = code; }
