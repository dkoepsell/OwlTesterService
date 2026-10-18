// "Start from what they have": turn a term list, spreadsheet, data dictionary,
// JSON Schema, or SQL DDL into candidate terms for the interview. Ingest only
// finds names, meanings and hints; it never classifies. Classification is
// proposed by the LLM and confirmed by a person.
import { createRequire } from 'node:module';
import { createCore } from './core.js';
import { InputError } from './service.js';

const require = createRequire(import.meta.url);
const ExcelJS = require('exceljs');
const MAX_TERMS = 60;

const clean = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
// claim_status, claimStatus, CLAIM_STATUS -> "Claim status"; short all-caps words (ID, NPI) are kept.
const human = s => clean(String(s).replace(/[_\-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2')).split(' ').map((w, i) => /^[A-Z0-9]{2,4}$/.test(w) && !/^[A-Z]+$/.test(String(s)) ? w : (i ? w.toLowerCase() : w[0].toUpperCase() + w.slice(1).toLowerCase())).join(' ');

function cellText(v) {
  if (v == null) return '';
  if (typeof v === 'object') { if (v.richText) return v.richText.map(r => r.text).join(''); if (v.text) return String(v.text); if (v.result != null) return String(v.result); }
  return String(v);
}

async function fromXlsx(buf) {
  const wb = new ExcelJS.Workbook();
  try { await wb.xlsx.load(buf); } catch (e) { throw new InputError("That spreadsheet couldn't be opened. Save it as .xlsx or .csv and try again."); }
  const ws = wb.worksheets.find(w => w.actualRowCount > 0);
  if (!ws) return { terms: [] };
  const rows = [];
  ws.eachRow({ includeEmpty: false }, row => rows.push(row.values.slice(1).map(cellText).map(clean)));
  const head = (rows[0] || []).map(h => h.toLowerCase());
  let ni = head.findIndex(h => /^(term|name|field|field name|column|column name|concept|label|entity|element|attribute)s?$/.test(h));
  const di = head.findIndex(h => /^(description|definition|meaning|notes?|comments?|business definition)$/.test(h));
  const ti = head.findIndex(h => /^(type|data type|datatype|format)$/.test(h));
  const hasHeader = ni >= 0 || di >= 0;
  if (ni < 0) ni = 0;
  const terms = [];
  rows.slice(hasHeader ? 1 : 0).forEach(r => {
    const name = r[ni]; if (!name || name.length > 80) return;
    terms.push({ name: /[a-z][A-Z]|_/.test(name) ? human(name) : name, desc: di >= 0 ? (r[di] || '').slice(0, 300) : '', hints: ti >= 0 && r[ti] ? `type: ${r[ti]}` : '' });
  });
  return { terms };
}

function fromJsonSchema(text) {
  let j; try { j = JSON.parse(text); } catch (e) { throw new InputError("That JSON doesn't parse."); }
  if (j && j.format === 'kindwork-model') throw new InputError('That is a Kindwork model. Open it with "Bring an ontology" instead.');
  const defs = { ...(j.$defs || {}), ...(j.definitions || {}) };
  const terms = [];
  const add = (key, s, parent) => {
    if (!s || typeof s !== 'object') return;
    const hints = [];
    if (s.type) hints.push(`type: ${[].concat(s.type).join('/')}`);
    if (s.format) hints.push(`format: ${s.format}`);
    if (s.enum) hints.push(`values: ${s.enum.slice(0, 8).join(', ')}`);
    const ref = s.$ref || (s.items && s.items.$ref);
    if (ref) hints.push(`links to ${human(ref.replace(/^.*\//, ''))}`);
    if (parent) hints.push(`field of ${parent}`);
    terms.push({ name: s.title || human(key), desc: clean(s.description).slice(0, 300), hints: hints.join('; ') });
  };
  const root = j.title || 'Record';
  if (j.type === 'object' || j.properties) add(root, { ...j, title: j.title || 'Record' }, null);
  Object.entries(defs).forEach(([k, s]) => add(k, s, null));
  Object.entries(j.properties || {}).forEach(([k, s]) => add(k, s, root));
  Object.entries(defs).forEach(([dk, d]) => Object.entries((d && d.properties) || {}).forEach(([k, s]) => add(k, s, d.title || human(dk))));
  return { terms, context: clean(j.description).slice(0, 500) };
}

function fromSql(text) {
  const terms = [], comments = new Map();
  const sql = String(text).replace(/--[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const m of sql.matchAll(/COMMENT\s+ON\s+(TABLE|COLUMN)\s+([\w."]+)\s+IS\s+'((?:[^']|'')*)'/gi)) comments.set(m[2].replace(/"/g, '').toLowerCase(), m[3].replace(/''/g, "'"));
  for (const m of sql.matchAll(/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w."`\[\]]+)\s*\(([\s\S]*?)\)\s*(?:;|$)/gi)) {
    const table = m[1].replace(/["`\[\]]/g, '').split('.').pop();
    const cols = [], links = [];
    m[2].split(/,(?![^()]*\))/).map(clean).forEach(def => {
      const fk = /^(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+([\w."]+)/i.exec(def);
      if (fk) { links.push(`${fk[1].trim()} links to ${human(fk[2].replace(/"/g, '').split('.').pop())}`); return; }
      if (/^(PRIMARY|UNIQUE|CHECK|CONSTRAINT|INDEX|KEY)\b/i.test(def)) return;
      const c = /^["`\[]?(\w+)["`\]]?\s+([\w(), ]+?)(\s|$)/.exec(def); if (!c) return;
      cols.push(c[1]);
      const ref = /REFERENCES\s+([\w."]+)/i.exec(def); if (ref) links.push(`${c[1]} links to ${human(ref[1].replace(/"/g, '').split('.').pop())}`);
      const inline = /COMMENT\s+'((?:[^']|'')*)'/i.exec(def); if (inline) comments.set(`${table}.${c[1]}`.toLowerCase(), inline[1]);
      if (/(status|state|type|kind|category|code)$/i.test(c[1]) || /_?(date|at|on)$/i.test(c[1])) {
        const one = table.replace(/s$/i, ''), col = c[1].replace(/_?(at|on)$/i, '');
        terms.push({ name: human(new RegExp('^' + one + '_', 'i').test(col) ? col : `${one} ${col}`), desc: comments.get(`${table}.${c[1]}`.toLowerCase()) || '', hints: `column ${c[1]} (${c[2].trim()}) of ${human(table)}` });
      }
    });
    terms.unshift({ name: human(table.replace(/s$/i, '')), desc: comments.get(table.toLowerCase()) || '', hints: [`table with columns ${cols.slice(0, 12).join(', ')}`, ...links].join('; ') });
  }
  return { terms };
}

// Returns { terms: [{name, desc, hints}], context? }.
export async function ingest(name, buf) {
  if (!Buffer.isBuffer(buf) || !buf.length) throw new InputError('The file is empty.');
  if (buf.length > 8 * 1024 * 1024) throw new InputError('That file is over 8 MB.');
  const ext = String(name || '').toLowerCase().split('.').pop();
  let out;
  if (ext === 'xlsx') out = await fromXlsx(buf);
  else if (ext === 'json') out = fromJsonSchema(buf.toString('utf8'));
  else if (ext === 'sql' || ext === 'ddl') out = fromSql(buf.toString('utf8'));
  else if (['csv', 'tsv', 'txt'].includes(ext)) out = { terms: createCore().parseTermList(buf.toString('utf8'), ext === 'csv') };
  else throw new InputError('Send a .csv, .tsv, .txt, .xlsx, .json (JSON Schema), or .sql file.');
  const seen = new Set(), terms = [];
  for (const t of out.terms) {
    const k = clean(t.name).toLowerCase(); if (!k || seen.has(k)) continue; seen.add(k);
    terms.push({ name: clean(t.name).slice(0, 80), desc: clean(t.desc).slice(0, 300), hints: clean(t.hints).slice(0, 200) });
  }
  if (!terms.length) throw new InputError(`No terms were found in ${name}.`);
  return { ok: true, terms: terms.slice(0, MAX_TERMS), truncated: terms.length > MAX_TERMS ? terms.length : 0, context: out.context || '' };
}
