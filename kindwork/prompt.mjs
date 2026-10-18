#!/usr/bin/env node
// Build a propose prompt with the vendored page's own builders (kindwork_core
// llm.js buildPrompt), for providers the sidecar does not call itself. Reads
// {kind, terms?, context?, task?} on stdin, writes {prompt} on stdout.
// Exit 0 on success, 2 on an input error, 1 otherwise.
import { buildPrompt } from '../kindwork_core/src/llm.js';
import { InputError } from '../kindwork_core/src/service.js';

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { raw += d; });
process.stdin.on('end', () => {
  try {
    const prompt = buildPrompt(JSON.parse(raw));
    process.stdout.write(JSON.stringify({ ok: true, prompt }));
  } catch (e) {
    const input = e instanceof InputError;
    process.stdout.write(JSON.stringify({ ok: false, error: input ? e.message : 'Internal error building the prompt.' }));
    process.exitCode = input ? 2 : 1;
  }
});
