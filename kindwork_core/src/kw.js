// Compiler front end for Kindwork keyword source (.kw).
//
//   app "Job site tracker"
//   namespace "https://example.org/kindwork/job-site-tracker"
//
//   status "Electrical license"
//     means "The state license that lets a worker do electrical work."
//     held_by "Worker"
//     issued_by "Licensing authority"
//
// Produces a kindwork-model object plus line-numbered diagnostics written for
// people, not logicians. Errors stop a build; warnings do not.

const KEYWORDS = ['thing', 'group', 'place', 'quality', 'tendency', 'function', 'role', 'authority', 'record', 'code', 'status', 'obligation', 'happening', 'moment', 'period'];
const REL_WORDS = {
  held_by: 'heldBy', issued_by: 'issuedBy', can_grant: 'scope', owed_by: 'owedBy', owed_to: 'owedTo',
  participant: 'participant', at: 'at', during: 'during', marks: 'marks', bearer: 'bearer',
  about: 'about', designates: 'designates', member: 'member',
  part_of: 'partOf', precedes: 'precedes', results_in: 'resultsIn', kept_on: 'keptOn', is_a: 'isA'
};
const REL_PLAIN = {
  heldBy: 'have a holder', issuedBy: 'have an issuer', scope: 'grant statuses', owedBy: 'have someone who owes it', owedTo: 'have someone who can claim it',
  participant: 'have participants', at: 'have a location', during: 'fall in a period', marks: 'mark a happening',
  bearer: 'have a bearer', about: 'be about something', designates: 'label something', member: 'have members',
  partOf: 'be part of something', precedes: 'come before something', resultsIn: 'result in something', keptOn: 'be kept on something'
};
const SIGNALS = ['held', 'startsEnds', 'unshown', 'extended', 'changes', 'assigned', 'measured'];
const orList = a => a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + (a.length > 2 ? ',' : '') + ' or ' + a[a.length - 1];
const KIND_PLAIN = {
  thing: 'a thing', group: 'a group', place: 'a place', quality: 'a quality', tendency: 'a tendency', function: 'a function',
  role: 'a role', authority: 'an authority', record: 'a record', code: 'a code', status: 'a status', obligation: 'an obligation',
  happening: 'a happening', moment: 'a moment', period: 'a period'
};

function lev(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return d[a.length][b.length];
}
function suggest(word, options) {
  let best = null, score = Infinity;
  for (const o of options) { const s = lev(word.toLowerCase(), o.toLowerCase()); if (s < score) { score = s; best = o; } }
  return score <= Math.max(2, Math.floor(word.length / 3)) ? best : null;
}
const quoted = s => { const m = /^"((?:[^"\\]|\\.)*)"\s*$/.exec(s.trim()); return m ? m[1].replace(/\\"/g, '"') : null; };

export function parseKw(source, slots) {
  const errors = [], warnings = [];
  const err = (line, message) => errors.push({ line, message });
  const terms = [], rels = [], lineOf = new Map();
  let app = null, namespace = '', cur = null, firstComment = null;
  const lines = String(source).replace(/\r\n?/g, '\n').split('\n');

  lines.forEach((raw, i) => {
    const line = i + 1;
    const text = raw.replace(/\s+#.*$/, '').replace(/^\s*#.*$/, '');
    if (/^\s*#/.test(raw) && firstComment === null) firstComment = raw.replace(/^\s*#\s*/, '').trim();
    if (!text.trim()) return;
    const indented = /^\s/.test(text);
    const t = text.trim();

    if (!indented) {
      cur = null;
      const m = /^([A-Za-z_]+)\s+(.*)$/.exec(t);
      if (!m) { err(line, `Expected a keyword and a quoted name, like: status "Electrical license".`); return; }
      const [, word, rest] = m;
      if (word === 'app' || word === 'namespace') {
        const v = quoted(rest);
        if (v === null) { err(line, `Put the ${word} in double quotes.`); return; }
        if (word === 'app') app = v; else namespace = v;
        return;
      }
      if (!KEYWORDS.includes(word)) {
        const s = suggest(word, KEYWORDS);
        err(line, `"${word}" isn't a keyword.${s ? ` Did you mean ${s}?` : ` The keywords are: ${KEYWORDS.join(', ')}.`}`);
        return;
      }
      const name = quoted(rest);
      if (!name) { err(line, `Put the name of the ${word} in double quotes.`); return; }
      const key = name.toLowerCase();
      if (lineOf.has(key)) { err(line, `"${name}" is already defined on line ${lineOf.get(key)}. Each term is defined once.`); return; }
      cur = { id: 't' + (terms.length + 1), name, keyword: word, definition: '', signals: {}, line, links: [] };
      terms.push(cur); lineOf.set(key, line);
      return;
    }

    if (!cur) { err(line, `This indented line doesn't belong to a term. Start it under a line like: thing "Worker".`); return; }
    if (t === 'self_declared') { cur.signals.selfDeclared = true; return; }
    if (t === 'owed_to public') { cur.signals.publicCorrelate = true; return; }
    const sm = /^signal\s+([a-z_]+)$/.exec(t);
    if (sm) {
      const key = sm[1].replace(/_([a-z])/g, (_, c) => c.toUpperCase());
      if (!SIGNALS.includes(key)) { const s = suggest(sm[1], SIGNALS.map(x => x.replace(/([A-Z])/g, '_$1').toLowerCase())); err(line, `"${sm[1]}" isn't a signal.${s ? ` Did you mean ${s}?` : ''}`); return; }
      cur.signals[key] = true; return;
    }
    const m = /^([A-Za-z_]+)\s+(.*)$/.exec(t);
    if (!m) { err(line, `Expected a link and a quoted name, like: held_by "Worker".`); return; }
    const [, word, rest] = m;
    if (word === 'means') {
      const v = quoted(rest); if (v === null) { err(line, 'Put the meaning in double quotes.'); return; }
      cur.definition = v; return;
    }
    const rel = REL_WORDS[word];
    if (!rel) {
      const s = suggest(word, [...Object.keys(REL_WORDS), 'means', 'self_declared']);
      err(line, `"${word}" isn't a link.${s ? ` Did you mean ${s}?` : ''}`);
      return;
    }
    const target = quoted(rest);
    if (target === null) { err(line, `Put the name after ${word} in double quotes.`); return; }
    cur.links.push({ rel, word, target, line });
  });

  // Resolve links once every term is known, so order in the file doesn't matter.
  const byName = new Map(terms.map(t => [t.name.toLowerCase(), t]));
  for (const t of terms) {
    const allowed = slots[t.keyword] || [];
    for (const l of t.links) {
      const target = byName.get(l.target.toLowerCase());
      if (!target) {
        const s = suggest(l.target, terms.map(x => x.name));
        err(l.line, `"${l.target}" isn't defined in this file.${s ? ` Did you mean "${s}"?` : ''}`);
        continue;
      }
      if (target === t) { err(l.line, `"${t.name}" can't be linked to itself.`); continue; }
      if (l.rel !== 'isA') {
        const slot = allowed.find(s => s.r === l.rel);
        if (!slot) {
          const owners = Object.keys(slots).filter(k => slots[k].some(s => s.r === l.rel));
          err(l.line, `"${t.name}" is ${KIND_PLAIN[t.keyword]}, and ${KIND_PLAIN[t.keyword].replace(/^an? /, 'a ')} can't ${REL_PLAIN[l.rel]}. ${l.word} is for ${orList(owners.map(o => KIND_PLAIN[o]))}.`);
          continue;
        }
        if (slot.to && !slot.to.includes(target.keyword)) {
          err(l.line, `${l.word} needs ${orList(slot.to.map(k => KIND_PLAIN[k]))}, but "${target.name}" is ${KIND_PLAIN[target.keyword]} (line ${target.line}).`);
          continue;
        }
        if (!slot.multi && rels.some(r => r.from === t.id && r.rel === l.rel)) {
          err(l.line, `"${t.name}" already has ${l.word}. ${KIND_PLAIN[t.keyword][0].toUpperCase() + KIND_PLAIN[t.keyword].slice(1)} takes only one.`);
          continue;
        }
      } else if (target.keyword !== t.keyword) {
        err(l.line, `is_a links two terms of the same kind, but "${t.name}" is ${KIND_PLAIN[t.keyword]} and "${target.name}" is ${KIND_PLAIN[target.keyword]}.`);
        continue;
      }
      rels.push({ from: t.id, rel: l.rel, to: target.id });
    }
  }
  if (!terms.length && !errors.length) err(1, 'The file defines no terms. Start with a line like: thing "Worker".');

  const model = {
    format: 'kindwork-model', version: '0.1', generator: 'kindwork-build',
    app: app || firstComment || 'Tracker', namespace,
    terms: terms.map(t => ({ id: t.id, name: t.name, definition: t.definition, keyword: t.keyword, answers: null, signals: t.signals, provenance: [] })),
    relations: rels
  };
  return { model, errors, warnings, lineOf: new Map(terms.map(t => [t.id, t.line])) };
}
