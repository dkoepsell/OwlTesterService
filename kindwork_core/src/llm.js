// The propose step. Builds the prompt with the page's own prompt builders, asks
// the model, and returns the parsed JSON for the page to apply and the person to
// confirm. The server never commits anything on the model's say-so.
//
// Env:
//   KINDWORK_LLM_KEY        API key (falls back to ANTHROPIC_API_KEY, then SOOL_ANTHROPIC_KEY)
//   KINDWORK_LLM_MODEL      model id, default claude-sonnet-5-5
//   KINDWORK_LLM_TIMEOUT_MS default 120000
//   KINDWORK_LLM_MOCK       path to a JSON file returned instead of calling the API (tests)
import fs from 'node:fs/promises';
import { createCore } from './core.js';
import { InputError } from './service.js';

const KEY = () => process.env.KINDWORK_LLM_KEY || process.env.ANTHROPIC_API_KEY || process.env.SOOL_ANTHROPIC_KEY || '';
const MODEL = () => process.env.KINDWORK_LLM_MODEL || 'claude-sonnet-5-5';
const TIMEOUT = () => Number(process.env.KINDWORK_LLM_TIMEOUT_MS || 120000);

export class UpstreamError extends Error { constructor(message, code = 'upstream_error', status = 502) { super(message); this.code = code; this.status = status; } }

export function buildPrompt(req) {
  const core = createCore();
  if (req.kind === 'task') {
    const task = String(req.task || '').trim();
    if (task.length < 40) throw new InputError('Write a few sentences about the task first.');
    if (task.length > 6000) throw new InputError('The description is too long. Trim it to a few paragraphs.');
    return core.extractionPrompt(task);
  }
  if (req.kind === 'terms') {
    const terms = (Array.isArray(req.terms) ? req.terms : []).filter(t => t && t.name).map(t => ({ name: String(t.name).slice(0, 80), desc: String(t.desc || '').slice(0, 300), hints: String(t.hints || '').slice(0, 200) }));
    if (!terms.length) throw new InputError('Send at least one term.');
    if (terms.length > 60) throw new InputError('Send at most 60 terms at a time.');
    return core.termsPrompt(terms, String(req.context || '').slice(0, 3000));
  }
  if (req.kind === 'relations') {
    const terms = (Array.isArray(req.terms) ? req.terms : []).filter(t => t && t.name && core.KW[t.kind]).map(t => ({ name: String(t.name).slice(0, 80), kind: t.kind, desc: String(t.desc || '').slice(0, 300) }));
    if (terms.length < 2) throw new InputError('Send at least two terms, each with its kind.');
    if (terms.length > 60) throw new InputError('Send at most 60 terms at a time.');
    return core.relationsPrompt(terms, String(req.context || '').slice(0, 3000));
  }
  throw new InputError('kind must be "task", "terms" or "relations".');
}

function parseJsonReply(text) {
  const t = String(text).trim();
  const tries = [t, (/```(?:json)?\s*([\s\S]*?)```/.exec(t) || [])[1], t.slice(t.indexOf('{'), t.lastIndexOf('}') + 1)];
  for (const x of tries) { if (!x) continue; try { return JSON.parse(x); } catch (e) {} }
  throw new UpstreamError('The model answered in the wrong shape. Try again, or send fewer terms.', 'invalid_json');
}

// Keep only relations between the terms sent, of a kind the interview would offer.
export function validRelations(terms, relations) {
  const core = createCore();
  const kindOf = new Map((terms || []).map(t => [String(t.name || '').toLowerCase(), t.kind]));
  const name = new Map((terms || []).map(t => [String(t.name || '').toLowerCase(), String(t.name)]));
  const out = [];
  for (const r of relations || []) {
    const f = String(r && r.from || '').toLowerCase(), t = String(r && r.to || '').toLowerCase();
    if (!kindOf.has(f) || !kindOf.has(t) || f === t) continue;
    const slot = (core.SLOTS[kindOf.get(f)] || []).find(s => s.r === r.rel);
    if (!slot || (slot.to && !slot.to.includes(kindOf.get(t)))) continue;
    if (out.some(x => x.from === name.get(f) && x.rel === r.rel && x.to === name.get(t))) continue;
    out.push({ from: name.get(f), rel: r.rel, to: name.get(t), why: String(r.why || '').slice(0, 240) });
  }
  return out;
}

// Returns { result, model } where result is { appName, terms, relations } as the page expects.
export async function propose(req) {
  const prompt = buildPrompt(req);
  let text;
  if (process.env.KINDWORK_LLM_MOCK) text = await fs.readFile(process.env.KINDWORK_LLM_MOCK, 'utf8');
  else {
    if (!KEY()) throw new UpstreamError('Proposing answers is not set up on this server.', 'sampling_disabled', 503);
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), TIMEOUT());
    try {
      const r = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST', signal: ctl.signal,
        headers: { 'content-type': 'application/json', 'x-api-key': KEY(), 'anthropic-version': '2023-06-01' },
        body: JSON.stringify({ model: MODEL(), max_tokens: 8000, messages: [{ role: 'user', content: prompt + '\n\nReply with the JSON only.' }] })
      });
      if (r.status === 429) throw new UpstreamError('Too many requests just now. Try again in a minute.', 'rate_limited', 429);
      if (!r.ok) throw new UpstreamError('The model could not be reached. Try again.');
      const j = await r.json();
      text = (j.content || []).filter(c => c.type === 'text').map(c => c.text).join('');
    } catch (e) {
      if (e instanceof UpstreamError) throw e;
      throw new UpstreamError(e.name === 'AbortError' ? 'The model took too long. Try again with fewer terms.' : 'The model could not be reached. Try again.');
    } finally { clearTimeout(timer); }
  }
  const result = parseJsonReply(text);
  if (req.kind === 'relations') {
    if (!result || !Array.isArray(result.relations)) throw new UpstreamError('The model answered in the wrong shape. Try again, or send fewer terms.', 'invalid_json');
    return { result: { relations: validRelations(req.terms, result.relations) }, model: process.env.KINDWORK_LLM_MOCK ? 'mock' : MODEL() };
  }
  if (!result || !Array.isArray(result.terms)) throw new UpstreamError('The model answered in the wrong shape. Try again, or send fewer terms.', 'invalid_json');
  if (req.kind === 'terms') {
    const asked = new Set(req.terms.map(t => String(t.name).toLowerCase()));
    result.terms = result.terms.filter(t => t && asked.has(String(t.name || '').toLowerCase()));
  }
  return { result, model: process.env.KINDWORK_LLM_MOCK ? 'mock' : MODEL() };
}
