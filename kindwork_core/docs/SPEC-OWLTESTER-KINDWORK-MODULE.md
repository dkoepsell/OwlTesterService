# OwlTester Kindwork Module: Build Spec

Draft 0.2.0, October 18, 2026. David R. Koepsell.
For: Claude Code, working in the OwlTester (OwlTesterService) repository on the Hetzner server.
Companions:
- `KINDWORK-ECOSYSTEM-SPEC.md` (interchange formats).
- The published Kindwork page, vendored here as `reference/core/kindwork.html`.

## 0. What the module is for

Non-ontologists can't say whether a "prior authorization" is a generically dependent continuant. They can say at once whether one can expire, whether it exists before anyone acts on it, and who can revoke it. Those answers fix the category. The module puts that interview inside OwlTester and puts OwlTester's reasoner behind it.

It must do five things. Every other section serves one of them.

1. **Classify by interview: questions in, categories out.** Each term gets two to eight plain yes-or-no questions; the answers pick one of fifteen keywords, each mapped to a BFO 2020 class. Nobody sees "occurrent" unless they flip "Show the ontology", which is also the teaching layer.
2. **Show consequences, not errors.** When answers collide, or the reasoner finds a class unsatisfiable, the person sees a card in their own words with choices. An example card: "You said a Claim can be in progress, and also that a member can hold one. Those are two things: the claiming, which happens, and the claim, which someone has. [It happens] [Someone holds it] [Split into two terms]". It is never "unsatisfiable class".
3. **Start from what they have.** The person pastes a term list, or uploads a spreadsheet, a data dictionary, JSON Schema, or SQL table definitions. An LLM proposes answers to the questions, the person confirms or corrects each term, and the reasoner gates what is committed. That is BFO-Agent's propose, gate, commit architecture, with a person in the confirm step.
4. **One model, two views.** The analyst answers questions in the browser. The engineer reads and edits the same model as keyword source, in the page or in git, and the linter checks both. They are not separate tools.
5. **Turn the model into working tools.** The module builds a standalone tracker app, OWL, SHACL, the keyword source, a classified list, and the model file. In the free first release, the classified list and the OWL are enough.

Interface rules that follow from the research and are not up for redesign:

- **Cards and tables, never diagrams of the model.** Diagrams stop being readable past a few dozen classes.
- **Dialogue over forms.** The interview asks one question at a time, and each answer decides the next.
- **Plain words by default, ontology on request.**

## 1. Phases

| Phase | Name | Who | What ships | Gate to next phase |
|---|---|---|---|---|
| P1 | **Free triage tool** | anyone, no account | Paste terms or a spreadsheet, have answers proposed, confirm, see conflict cards, download the classified list (CSV) and the ontology (Turtle). A Straddle Triage offer on the results page. Page mode `triage`. | 25 real term lists run through it, with confirmation rates logged (section 9) |
| P2 | **Full Kindwork in OwlTester** | signed-in OwlTester users | Every way in (task, terms, ontology, documents), reasoner gate on confirm, reasoner check in Resolve, the source view, the build kit with tracker. Page mode `full`. | P1 data shows the questions work (ADJUDICATE A9) |
| P3 | **CI linter** | engineers | `kindwork-core lint` and `build` as a GitHub Action over `.kw` files in a repo. | none |

Build P1 first and ship it. P2 and P3 reuse every piece P1 needs, so nothing in P1 is throwaway.

## 2. Architecture: one page, two hosts

```
Browser                                OwlTester server
───────                                ────────────────
Kindwork page (vendored, unchanged)    /kindwork           serves the page with a host config
  window.KINDWORK_HOST = {               injected before its scripts
    api: '/kindwork/v1',
    mode: 'triage' | 'full' }
  ── POST /propose ─────────────────►  sidecar: propose ──► LLM (OwlTester's key)
  ── POST /ingest  ─────────────────►  sidecar: ingest
  ── POST /check   ─────────────────►  sidecar: prepare ──► OwlTester reasoner ──► sidecar: findings
  ── POST /build, /import, /lint ───►  sidecar
```

**The page.** `reference/core/kindwork.html` is the same page published as the Kindwork artifact on claude.ai. When `window.KINDWORK_HOST` is set, the page:

- uses the server for proposing answers (`/propose`), reading files (`/ingest`), and checking (`/check`);
- saves files as ordinary browser downloads;
- runs the reasoner gate when a term is confirmed;
- in `triage` mode, limits itself to the P1 surface.

Without the config, the page runs as the claude.ai artifact. The host code is already in the page; you do not edit it.

**The sidecar.** `reference/bin/kindwork-core.mjs` takes one JSON request on stdin and returns one JSON reply on stdout. It runs the page's own code in an isolated `vm` context, so the server and the browser can never disagree. OwlTester calls it as a subprocess.

**Your job.** Serve the page with its config, wire routes to the sidecar, connect OwlTester's reasoner for `check`, add the MCP tools, and write the module tests. You are not reimplementing the interview, the generators, the compiler, the ingest parsers, or the prompts. All of them are in the page or the sidecar and are covered by the 19 reference tests.

## 3. Bundle layout

```
SPEC-OWLTESTER-KINDWORK-MODULE.md   this file
KINDWORK-ECOSYSTEM-SPEC.md           interchange formats
reference/
  core/kindwork.html                 the page: interview, cards, generators, compiler, prompts
  src/core.js                        runs the page's code in a vm context per call
  src/service.js                     build, import, lint (load), prepare, findings, check
  src/ingest.js                      CSV/TSV/TXT, XLSX, JSON Schema, SQL DDL -> candidate terms
  src/llm.js                         propose: prompt from the page, one model call, JSON back
  src/reasoner.js                    REFERENCE ONLY: ROBOT/HermiT runner showing the result shape
  bin/kindwork-core.mjs              the sidecar
  test/acceptance.test.js            A1 to A19
  test/fixtures/                     job-site model (.kw, .ttl, shapes, .kindwork.json), straddle fixtures
  test/fixtures/ingest/              claims-terms.csv, data-dictionary.xlsx, claims-schema.json, claims.sql, mock-proposal.json
  vendor/                            bfo-core.owl, iao-bridge.ttl, catalog-v001.xml
  package.json, package-lock.json    exact versions, Node 20 or later
```

## 4. Term lifecycle and the gate

Every term is in one of four states. Only one of them, *proposed*, is stored; the others are derived.

| State | How it gets there | Enters the build |
|---|---|---|
| **Needs answers** | added by hand, or the LLM gave no usable answers | no |
| **Proposed** | the LLM answered; stored as `state: "proposed"` | no |
| **Held back** | confirmed by a person, but blocked | no |
| **Committed** | confirmed, and nothing blocks it | yes |

A term is **blocked** when it has an open conflict card of severity `partition` or `within`, or an open reasoner finding (`verdict: "fail"`, check `coherence` or `consistency`) naming its IRI. Recognition-chain cards are reported but do not block, because the tool can carry them as notes. A license with no issuer is still a license.

Rules:

1. Nothing the LLM says is committed until a person presses Confirm on that term. There is no "confirm all".
2. On a server host, Confirm runs `/check` before the term counts as committed (the page does this).
3. A check replaces earlier findings. It covers every confirmed term, including held-back ones, so that resolving a conflict can release a term.
4. Editing an answer on a committed term re-evaluates the gate immediately.
5. The model file records `state` and a derived `committed` flag for every term (see the ecosystem spec, section 3).

## 5. Sidecar contract

Invocation: `node reference/bin/kindwork-core.mjs`, request on stdin, reply on stdout. Exit codes: 0 for success, 2 for an input error (the reply carries `errors`), 3 for a model or LLM error (the reply carries `code` and `status`), and 1 for internal errors.

| op | request | reply |
|---|---|---|
| `health` | `{}` | `{ ok, core, reasoner }` |
| `ingest` | `{ name, base64 }` | `{ ok, terms: [{name, desc, hints}], truncated, context }` |
| `propose` | `{ kind: "terms", terms: [{name, desc, hints}], context? }` or `{ kind: "task", task }` | `{ ok, result: {appName, terms, relations}, model }` |
| `build` | `{ source, name, format? }` | `{ ok, input, app, slug, namespace, recordTypes, unplaced, proposed, heldBack, warnings, files }` |
| `import` | `{ source, name }` | `{ ok, ..., ontology: {classes, imported}, warnings, model }` |
| `lint` | `{ source, name }` | `{ ok, input, errors: [], warnings }` (with errors: exit 2) |
| `prepare` | `{ source, name }` | `{ input, ontology: { text, ext } }` |
| `findings` | `{ source, name, reasoner }` | `owltester-findings` |

- `source` is keyword source, a `kindwork-model` JSON string, Turtle, or RDF/XML. The `.kw` extension in `name` disambiguates keyword source.
- Inputs over 8 MB are refused. `propose` takes at most 60 terms, or a task of at most 6,000 characters.
- `propose` reads its key from `KINDWORK_LLM_KEY`, then `ANTHROPIC_API_KEY`, then `SOOL_ANTHROPIC_KEY`. The model is `KINDWORK_LLM_MODEL` (default `claude-sonnet-5-5`). It drops any term the model invents. `KINDWORK_LLM_MOCK=<file>` replaces the call in tests.
- `ingest` finds names, meanings, and hints only; it never classifies:
  - **CSV/TSV/XLSX:** a header row named term, name, field, or column, and description, definition, or meaning, is used when present.
  - **JSON Schema:** objects, definitions, and properties, with type, format, enum, and `$ref` as hints.
  - **SQL:** tables, plus status, type, code, and date columns, with foreign keys as hints.

## 6. Reasoner integration

For `check`, run OwlTester's existing pipeline on `prepare`'s `ontology.text`, then hand `findings` this object:

```json
{ "status": "ok", "consistent": true,
  "unsatisfiable": [ { "iri": "http://ex.org/x#Episode", "label": "Manic episode", "partition": true,
                       "axioms": ["Manic episode SubClassOf Mental disorder", "Mental disorder SubClassOf disposition", "Manic episode SubClassOf process", "continuant DisjointWith occurrent"] } ],
  "axioms": [], "detail": "" }
```

1. **Load BFO offline.** Resolve the BFO import to `vendor/bfo-core.owl` through the catalog, and always merge `vendor/iao-bridge.ttl`. Without the bridge, a class under both quality and information content entity looks satisfiable.
2. **`status` is three-valued.** It is `ok` only when the run completed. Otherwise it is `timeout`, `error`, or `unavailable`, with a one-sentence `detail` written for a non-specialist. The sidecar turns these into `undetermined` findings, never `pass`.
3. **Inconsistency.** `consistent: false` puts one minimal explanation, as plain axioms, in top-level `axioms`.
4. **Unsatisfiable classes.** List every one, with IRIs exactly as given.
   - `axioms` is one justification as `Label SubClassOf Label` lines: labels, not IRIs or links.
   - `partition` is `true` when the justification uses continuant/occurrent disjointness, `false` for any other disjointness, and `null` if unknown.
5. **Cross-check.** If HermiT and Pellet disagree about a class, leave it out of `unsatisfiable` and set `detail: "HermiT and Pellet disagree on <labels>."`.
6. **Limits.** Timeout `KINDWORK_REASONER_TIMEOUT_MS`, default 60000; at most 2 concurrent runs for this module.

`reference/src/reasoner.js` produces this shape with ROBOT and is the oracle. On `straddle-imports-bfo.ttl`, your pipeline must give the same findings as A11.

## 7. Routes

Mount under `/kindwork/v1`. Bodies are JSON; replies are JSON unless noted.

| Route | Body | Success | Errors |
|---|---|---|---|
| `GET /kindwork` | none | the page, with the host config injected (below) | |
| `GET /kindwork/v1/health` | none | `200 { ok, core, reasoner }` | `503` |
| `POST /kindwork/v1/ingest` | `{ name, base64 }` | `200 { terms, truncated, context }` | `422 { error }` |
| `POST /kindwork/v1/propose` | `{ kind, terms? , context?, task? }` | `200 { result, model }` | `422`; `429 { code: "rate_limited", error }`; `503 { code: "sampling_disabled", error }`; `502 { code, error }` |
| `POST /kindwork/v1/check` | `{ source, name }` | `200` owltester-findings | `422`; reasoner trouble is a `200` with an undetermined finding, never `500` |
| `POST /kindwork/v1/build` | `{ source, name, format? }` | `200` build reply; with `Accept: application/zip`, a zip of `files` under a folder named `slug` | `422 { error, errors }` |
| `POST /kindwork/v1/import` | `{ source, name }` | `200` import reply | `422` |
| `POST /kindwork/v1/lint` | `{ source, name }` | `200 { errors: [], warnings }` | `422 { errors }` |

**Host config injection.** Insert this immediately after the `<meta name="claude:viewport-fit-sides">` line of the page, before any of its scripts. Do not otherwise modify the file.

```html
<script>window.KINDWORK_HOST = { api: '/kindwork/v1', mode: 'triage', cta: { title: '…', text: '…', href: '…', label: '…' } };</script>
```

`mode` is `triage` for P1 and `full` for P2. `cta` is optional; when it is omitted, the page shows its own Straddle Triage offer.

**Limits and access.**
- **Bodies:** 8 MB, as `413`.
- **P1 rate limits:** anonymous, so `/propose` is limited to 20 calls per IP per hour and 300 per day overall, and `/check` to 60 per IP per hour. Return `429` with `code: "rate_limited"`.
- **P2 auth:** reuse OwlTester's sign-in. If there is none, require `Authorization: Bearer $KINDWORK_TOKEN`; the page passes it through `KINDWORK_HOST.headers`.

**Every reply** carries `X-Kindwork-Core: <first 12 hex of sha256(core/kindwork.html)>`.

**Retention.** Nothing a person sends is stored after the reply, except the P1 log in section 9, which keeps counts, not content.

## 8. MCP tools

Register on OwlTester's MCP server if it has one; otherwise add a stateless streamable-HTTP endpoint at `/kindwork/mcp` (`@modelcontextprotocol/sdk` 1.29.0), with a new server and transport per request. Each tool returns one JSON text block. An input error is a normal result with `isError: true`, never a protocol error.

| Tool | Input | Register with this description |
|---|---|---|
| `kindwork_propose` | `terms: {name, desc?, hints?}[]`, `context?` | Propose answers to Kindwork's classification questions for a list of terms. Returns proposals only; a person must confirm each term before it counts. |
| `kindwork_ingest` | `name`, `base64` | Read a term list, spreadsheet, data dictionary, JSON Schema or SQL file and return candidate terms with meanings and hints. Does not classify. |
| `kindwork_lint` | `source`, `name?` | Check Kindwork keyword source and return line-numbered errors and warnings in plain language. Does not build. |
| `kindwork_check` | `source`, `name?` | Run the OwlTester reasoner on a Kindwork model, keyword source or ontology and return findings in plain language, three-valued: fail, undetermined, pass. |
| `kindwork_build` | `source`, `name?` | Compile a Kindwork model or keyword source into BFO 2020 OWL, SHACL shapes, a standalone tracker app, keyword source, a classified list and a model file. |
| `kindwork_import` | `source`, `name?` | Read an ontology (Turtle or RDF/XML) or Kindwork model into a Kindwork model, placing each class by its BFO 2020 ancestors and flagging straddles. |

## 9. P1 measurement

The first release exists to find out whether the questions work for non-ontologists. That is ADJUDICATE A8 in the keyword spec. Log one row per session, with no term text:

- how many terms came in, and from which source type;
- how many terms Claude proposed;
- how many were confirmed unchanged, and how many were confirmed after a person changed an answer (and which question ids changed);
- how many were held back, and how many cards of each type were raised and resolved, and how;
- whether the results were downloaded, and whether the Straddle Triage link was clicked.

Put the log where OwlTester keeps its own usage data, with a 12-month retention.

## 10. Updating the page

The vendored page is a copy of the published Kindwork artifact. To update it:

1. Replace `reference/core/kindwork.html`.
2. Run the reference tests and the module tests.
3. Commit with the new `X-Kindwork-Core` hash.

`src/core.js` refuses to start without the page's `__KINDWORK_EXPORT__` hook and `runtime-css` block. Changes to the interview, the cards, the generators, or the prompts go into Kindwork first, and are then copied here. Never edit the vendored page in place.

## 11. Hard stops

- Never commit a term a person has not confirmed, and never offer "confirm all".
- Never report `pass` for anything the reasoner did not finish.
- Never rewrite, normalize, or re-mint a class IRI from the input.
- Never put logic notation, IRIs, or `owl:`/`BFO_` tokens in a card, a finding's `title` or `explanation`, or a diagnostic `message`. They are allowed only in collapsed axioms and behind the ontology toggle.
- Never send `/propose` a prompt built anywhere but the page's `extractionPrompt` or `termsPrompt`, and never expose a route that takes a raw prompt.
- Never store submitted terms, files, or models after the reply, beyond the counts in section 9.
- Never edit the vendored page in place, and never let a reasoner failure become an HTTP 500.
- No em-dash (U+2014) in any generated file, page string, message, or doc in this module. CI asserts it.

## 12. Acceptance

**Reference tests.** In `reference/`, run `npm ci && npm test`. A1 to A19 must pass in OwlTester's CI. A11 needs ROBOT; if OwlTester keeps no ROBOT, B4 replaces it.

| Test | Proves |
|---|---|
| A1 | `.kw` builds 13 types; the gate holds back Contract period (it can be "extended" yet is a span of time) |
| A2 | compiler errors: right lines, plain messages, no notation |
| A3 | keyword source, model, and OWL round-trip (177 and 188 triples while one term is held back) |
| A4 | the tracker is one standalone page with schema and runtime |
| A5 | interview conflicts become line-numbered warnings |
| A6 | import places classes by BFO ancestors and flags both straddle kinds |
| A7 | findings from any reasoner result, three-valued |
| A8 | an ontology is checked as given; anything else is compiled first |
| A9 | sidecar contract and exit codes |
| A10 | no em-dash in generated files |
| A11 | reference HermiT run finds the partition and within straddles |
| A12 | the source view holds the whole model: undecided and proposed terms round-trip |
| A13 | resolving the conflict releases the held-back term (14 types) |
| A14 | term lists: plain lines, meanings, tabs, CSV with headers and quotes, bullets, duplicates |
| A15 | proposals fill only proposed terms, drop invented ones, never confirm; the Claim card is raised |
| A16 | ingest of CSV, XLSX data dictionary, JSON Schema, and SQL DDL |
| A17 | propose builds its prompt from the page and filters to the terms asked about |
| A18 | the source view refuses to remove terms silently |
| A19 | sidecar ingest and propose, including the no-key `503` path |

**Module tests you add** (route tests with supertest or the equivalent; UI tests with Playwright against `/kindwork`):

| Test | Pass condition |
|---|---|
| B1 | `GET /kindwork` returns the page with exactly one injected `KINDWORK_HOST` script before the page's first script, and the page renders four steps in `triage` mode, five in `full` |
| B2 | P1 flow in Playwright: paste the five terms in `claims-terms.csv`, Propose (mock LLM), all five show "proposed"; confirm Prior authorization; it shows "Committed" after the check; Claim shows its held-versus-happening card; Results lists the 5 terms with statuses; both downloads work |
| B3 | Upload `data-dictionary.xlsx` through the page: the text area fills with the 3 terms and their meanings |
| B4 | `POST /check` with `straddle-imports-bfo.ttl` through OwlTester's pipeline: `{consistent: true, coherent: false}`, one partition and one within coherence finding, plain axioms |
| B5 | `POST /check` with `job-site-tracker.kindwork.json`: consistent, coherent, plus three interview findings (two chain, one partition) |
| B6 | Forced reasoner timeout: `200`, undetermined finding, `verdict {consistent: null, coherent: null}`; in the page, the confirmed term shows "confirmed but not yet checked" |
| B7 | `/propose` with no key configured: `503 sampling_disabled`; the page shows the "answer yourself" path |
| B8 | Rate limit: the 21st `/propose` from one IP within an hour returns `429`; the page shows "Too many requests just now" |
| B9 | `POST /build` with `Accept: application/zip`: a zip of six files under `job-site-tracker/` |
| B10 | MCP `tools/list` shows six tools; `kindwork_lint` on the A2 source returns `isError: true` with line 2 first |
| B11 | `/build` with a 9 MB body: `413` |
| B12 | No U+2014 in any route reply, page string as rendered in both modes, or module doc |
| B13 | The section 9 log for a B2 run holds counts and question ids only; grep finds no term text |

## 13. Out of scope

- Generating terms from documents. That is BFO-Agent, through its own adapter in the ecosystem spec.
- Hosting built trackers at a URL (A5).
- Accounts and saved models in P1. The page keeps a draft in the person's own browser only.
- OWL functional syntax and OWL/XML input. These are refused with a message to re-save.

## ADJUDICATE

- **A1. Sidecar or port.** A sidecar keeps one source of truth at the cost of a Node dependency. A port means maintaining a second copy of the interview, prompts, generators, and compiler, and it will drift. Recommended: sidecar.
- **A2. Spawn per call or warm pool.** Spawning measured 100 to 130 ms per call, almost all of it Node startup. In-process, the core costs about 2 ms. Start by spawning, and add a 2-worker pool with line-delimited JSON if p95 matters.
- **A3. LLM cost in P1.** Anonymous `/propose` spends OwlTester's key. The section 7 limits cap it. Decide the daily ceiling, and whether P1 needs an email before Propose. Recommended: no email, because the email question costs more leads than the calls cost money.
- **A4. Lead capture.** Should the Straddle Triage link pass the session's anonymous counts (terms, held back, cards) so the triage call starts informed? It is a query string on a link the person chooses to click, and it contains no term text.
- **A5. Tracker hosting.** Out of scope until a client asks; it needs storage.
- **A6. IAO bridge or full IAO.** The bridge is one axiom and keeps the reasoner fast; full IAO catches more but loads slower.
- **A7. Disagreement policy.** Section 6 rule 5 marks HermiT/Pellet disagreement as undetermined. Confirm that it matches OwlTester's existing cross-check.
- **A8. Where it lives.** `/kindwork` on OwlTester's host, or a subdomain. This matters for the P1 public URL and for any later connector.
- **A9. When the questions are good enough.** A proposed bar for moving to P2: at least 80 percent of proposed terms confirmed without a changed answer, and no single question changed on more than 15 percent of the terms that reach it. Questions over that line get rewritten in the keyword spec first.
- **A10. The natural-function question.** P1 confirms `function` only for made things, and routes natural cases to `tendency`, per keyword spec A2. This is visible to the public, so settle it before P1 ships.
