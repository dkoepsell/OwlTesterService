#!/usr/bin/env node
// Build a propose prompt with the vendored page's own builders (kindwork_core
// llm.js buildPrompt), for providers the sidecar does not call itself. Reads
// {kind, terms?, context?, task?} on stdin, writes {prompt} on stdout. With
// {op: "relations", terms, relations} it instead filters a model's suggested
// relations to the ones the interview allows, and writes {relations}.
// Exit 0 on success, 2 on an input error, 1 otherwise.
import { buildPrompt, validRelations } from '../kindwork_core/src/llm.js';
import { InputError } from '../kindwork_core/src/service.js';

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { raw += d; });
process.stdin.on('end', () => {
  try {
    const req = JSON.parse(raw);
    if (req.op === 'relations') { process.stdout.write(JSON.stringify({ ok: true, relations: validRelations(req.terms, req.relations) })); return; }
    const prompt = buildPrompt(req);
    process.stdout.write(JSON.stringify({ ok: true, prompt }));
  } catch (e) {
    const input = e instanceof InputError;
    process.stdout.write(JSON.stringify({ ok: false, error: input ? e.message : 'Internal error building the prompt.' }));
    process.exitCode = input ? 2 : 1;
  }
});
