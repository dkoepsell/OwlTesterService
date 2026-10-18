# OwlTester Kindwork Module: Build Spec

Draft 0.1.0, October 18, 2026. David R. Koepsell.
For: Claude Code, working in the OwlTester (OwlTesterService) repository on the Hetzner server.
Companion: `KINDWORK-ECOSYSTEM-SPEC.md` (interchange formats). This spec implements its OwlTester side and adds a build service.

## 0. What you are building

A module inside OwlTester that does four things for Kindwork models:

1. **Build.** It compiles a Kindwork model or keyword source (`.kw`) into BFO 2020 OWL, SHACL shapes, a standalone tracker app, the keyword source and the model file.
2. **Import.** It reads an existing ontology (Turtle or RDF/XML) into a Kindwork model, placing each class by its BFO ancestors.
3. **Lint.** It checks keyword source and returns line-numbered errors and warnings in plain language.
4. **Check.** It runs OwlTester's own reasoner over a model or ontology and returns an `owltester-findings` file that Kindwork shows as cards.

All four are exposed as HTTP routes and as MCP tools, with a small page in OwlTester's UI.

The logic already exists and is tested. This bundle carries a reference implementation in `reference/` (Node.js, 11 passing acceptance tests). Your job is integration, not reinvention. Do not reimplement the generators, the compiler, or the import walk in another language unless ADJUDICATE A1 is settled that way.

## 1. Bundle layout

```
SPEC-OWLTESTER-KINDWORK-MODULE.md   this file
KINDWORK-ECOSYSTEM-SPEC.md           interchange formats (kindwork-model, owltester-findings)
reference/
  core/kindwork.html                 vendored Kindwork page: the single source of the generators
  src/core.js                        runs the page's code in an isolated vm context per call
  src/kw.js                          keyword-source compiler (parser, resolver, diagnostics)
  src/service.js                     build, import, lint (load), prepare, findings, check
  src/reasoner.js                    REFERENCE ONLY: ROBOT/HermiT runner showing the result shape
  bin/kindwork-core.mjs              the sidecar: one JSON request on stdin, one JSON reply on stdout
  test/acceptance.test.js            A1 to A11
  test/fixtures/                     job-site-tracker.{kw,ttl,-shapes.ttl,kindwork.json}, straddle*.ttl, findings-sample.json
  vendor/bfo-core.owl                BFO 2020 core, from BFO-ontology/BFO-2020 (21838-2/owl)
  vendor/iao-bridge.ttl              one axiom: IAO_0000030 SubClassOf BFO_0000031
  vendor/catalog-v001.xml            maps the BFO purls to the local file
  package.json, package-lock.json
```

`robot.jar` is not bundled (93 MB). The reference reasoner fetches nothing; install ROBOT 1.9.6 into `reference/vendor/` only if you want A11 to run.

## 2. Architecture

```
OwlTester request (HTTP or MCP)
  │
  ├─ build / import / lint ──► kindwork-core sidecar (node) ──► JSON reply
  │
  └─ check
       1. sidecar: prepare  ──► ontology text to reason over
       2. OwlTester's own reasoner pipeline (HermiT, Pellet cross-check if configured)
            ──► reasoner result object (section 4)
       3. sidecar: findings ──► owltester-findings JSON
```

**Why a sidecar.** The generators live in the Kindwork page itself. `src/core.js` loads that page and runs its scripts in a fresh `vm` context per call, so the hosted build and the browser can never disagree. Porting would create a second copy that drifts. Keep the page vendored and call it.

**Statelessness.** The module stores nothing. Every request carries its whole input, and every reply is complete. Temp files are deleted after each reasoner run.

## 3. Sidecar contract

Invocation: `node reference/bin/kindwork-core.mjs`, request on stdin, reply on stdout, both JSON. Exit 0 is success, 2 is an input error (the reply carries diagnostics), and 1 is an internal error.

| op | request | reply |
|---|---|---|
| `health` | `{}` | `{ ok, core, reasoner }` |
| `build` | `{ source, name, format? }` | `{ ok, input, app, slug, namespace, recordTypes[], unplaced[], warnings[], files{name: text} }` |
| `import` | `{ source, name }` | `{ ok, input, app, slug, recordTypes[], ontology{classes, imported}, warnings[], model }` |
| `lint` | `{ source, name }` | `{ ok, input, errors: [], warnings[] }` (errors come back with exit 2) |
| `prepare` | `{ source, name }` | `{ ok, input, ontology{ text, ext } }` |
| `findings` | `{ source, name, reasoner }` | an `owltester-findings` object |

- `source` is text: keyword source, a `kindwork-model` JSON string, Turtle, or RDF/XML. `name` is the file name. Its extension disambiguates `.kw`.
- `format` overrides detection: `kw`, `json`, `turtle`, `rdfxml`.
- Diagnostics are `{ line, message }` for errors and `{ line, term, severity, message }` for warnings. `line` is null for non-keyword inputs.
- Input over 8 MB is refused with exit 2.

## 4. Reasoner integration (the only new logic you write)

For `check`, run OwlTester's existing pipeline on `prepare`'s `ontology.text` and hand the sidecar this object:

```json
{
  "status": "ok",
  "consistent": true,
  "unsatisfiable": [
    { "iri": "http://ex.org/x#Episode", "label": "Manic episode", "partition": true,
      "axioms": ["Manic episode SubClassOf Mental disorder", "Mental disorder SubClassOf disposition", "Manic episode SubClassOf process", "continuant DisjointWith occurrent"] }
  ],
  "axioms": [],
  "detail": ""
}
```

Requirements:

1. **Load BFO offline.** Resolve `owl:imports <http://purl.obolibrary.org/obo/bfo.owl>` to `vendor/bfo-core.owl` through the catalog, and always merge `vendor/iao-bridge.ttl`. Without the bridge, a class under both quality and IAO information content entity looks satisfiable. The reference test A11 depends on this.
2. **`status`** is `ok` only when the reasoner ran to completion. A timeout, a parse failure, or no reasoner gives `timeout`, `error`, or `unavailable` with a one-sentence `detail` written for a non-specialist. The sidecar turns these into `undetermined` findings. Never `pass`.
3. **`consistent: false`** puts one minimal inconsistency explanation, as plain axioms, in top-level `axioms`.
4. **`unsatisfiable`** lists every unsatisfiable named class, IRIs exactly as in the input. For each:
   - **`axioms`** is one justification, rendered as `Label SubClassOf Label` lines: labels not IRIs, with no Markdown links.
   - **`partition`** is `true` when the justification uses BFO's continuant/occurrent disjointness, `false` when it uses another disjointness, and `null` if unknown.
5. **Cross-check.** If OwlTester runs HermiT and Pellet and they disagree on consistency or on a class, report that class with `status` still `ok`, but omit it from `unsatisfiable`, and add `detail: "HermiT and Pellet disagree on <labels>."`. The sidecar then emits an undetermined finding.
6. **Timeout.** Use the env `KINDWORK_REASONER_TIMEOUT_MS`, default 60000. Allow at most 2 concurrent reasoner runs for this module.

`reference/src/reasoner.js` produces exactly this shape with ROBOT (`merge`, `reason`, `explain --mode unsatisfiability`). Use it as the oracle: on `straddle-imports-bfo.ttl` your pipeline's result must yield the same findings as A11.

## 5. HTTP routes

Mount under OwlTester's app at `/kindwork/v1`. JSON in, JSON out, unless noted.

| Method and path | Body | Success | Errors |
|---|---|---|---|
| `GET /kindwork/v1/health` | none | `200 { ok, core, reasoner }` | `503` if the sidecar fails |
| `POST /kindwork/v1/build` | `{ source, name, format? }` | `200` build reply; with `Accept: application/zip`, `200` a zip of `files` in a folder named `slug` | `422 { error, errors[] }` |
| `POST /kindwork/v1/import` | `{ source, name }` | `200` import reply | `422` |
| `POST /kindwork/v1/lint` | `{ source, name }` | `200 { errors: [], warnings[] }` | `422 { errors[] }` |
| `POST /kindwork/v1/check` | `{ source, name }` | `200` owltester-findings | `422`; never `500` for reasoner trouble (that is an undetermined finding) |

- Body limit 8 MB, enforced as `413`.
- Auth: reuse OwlTester's existing scheme. If it has none, require `Authorization: Bearer $KINDWORK_TOKEN` on every route but health.
- CORS: allow the Kindwork artifact origin only if A3 is decided for direct calls. Default: no CORS.
- Response header `X-Kindwork-Core: <sha256 of core/kindwork.html, first 12 hex>` on every reply, so drift is visible.

## 6. MCP tools

If OwlTester already runs an MCP server, register these tools on it. If not, add a stateless streamable-HTTP MCP endpoint at `/kindwork/mcp` with `@modelcontextprotocol/sdk` 1.29.0 (already in `reference/package.json`), with no sessions, and a new server and transport per request.

| Tool | Input | Output (as one JSON text block) | Description to register, verbatim |
|---|---|---|---|
| `kindwork_build` | `source: string`, `name?: string` | build reply, `files` included | Compile a Kindwork model or keyword source into BFO 2020 OWL, SHACL shapes, a standalone tracker app, keyword source and a model file. Returns the files and any warnings. |
| `kindwork_lint` | `source`, `name?` | `{ errors, warnings }` | Check Kindwork keyword source and return line-numbered errors and warnings in plain language. Does not build. |
| `kindwork_import` | `source`, `name?` | import reply | Read an ontology (Turtle or RDF/XML) or Kindwork model and return a Kindwork model, with each class placed by its BFO 2020 ancestors and straddles flagged. |
| `kindwork_check` | `source`, `name?` | owltester-findings | Run the OwlTester reasoner on a Kindwork model, keyword source or ontology and return findings in plain language, three-valued: fail, undetermined, pass. |

An input error is a normal tool result with `isError: true` and the diagnostics in the text, never a protocol error.

## 7. UI page

Add one page to OwlTester, reachable from its nav as **Kindwork**. Match OwlTester's existing look. Do not import Kindwork's styles.

- A text area and a file picker accepting `.kw`, `.json`, `.ttl`, `.owl`, and `.rdf`.
- Three buttons: Lint, Check, and Build (downloads the zip).
- Lint shows errors as a list with line numbers; clicking one moves the cursor to that line in the text area. Warnings are listed below, separately.
- Check shows each finding with its severity label (Crosses the core divide, Within one side, Recognition chain, Note), a verdict pill (Fails, Undetermined, Passes), title, explanation, and the axioms in a collapsed disclosure. A button saves the findings file as `<slug>.findings.json` for import into Kindwork.
- A link to Kindwork for people who want the interview instead.

No logic notation appears outside the collapsed axioms.

## 8. Updating the core

`reference/core/kindwork.html` is a copy of the published Kindwork artifact. To update it:

1. Replace the file with the new page.
2. Run the tests.
3. Commit with the new `X-Kindwork-Core` hash in the message.

`src/core.js` refuses to start if the page lacks the `__KINDWORK_EXPORT__` hook or the `runtime-css` block. Never edit the vendored page by hand: changes go into Kindwork first and are copied here.

## 9. Hard stops

- Never report `pass` for anything the reasoner did not finish.
- Never rewrite, normalize, or re-mint a class IRI from the input.
- Never put logic notation, IRIs, or `owl:`/`BFO_` tokens in a finding's `title` or `explanation`, or in a diagnostic `message`.
- Never edit `core/kindwork.html` in place.
- Never let a reasoner failure surface as HTTP 500.
- Never persist a request's input after the reply is sent.
- No em-dash (U+2014) in any generated file, message, UI string, or in this module's docs. CI asserts it (A10 and B7).

## 10. Acceptance

**Reference tests.** In `reference/`, run `npm ci && npm test`. All of A1 to A11 must pass in OwlTester's CI. A11 needs ROBOT; if OwlTester does not keep ROBOT, A11 is replaced by B3.

| Test | Proves |
|---|---|
| A1 | `.kw` builds 14 record types and six files |
| A2 | compiler errors: right lines, plain messages, no notation |
| A3 | keyword source, model and OWL round-trip (190 and 216 triples; keywords stable) |
| A4 | the tracker is one standalone page with schema and runtime |
| A5 | interview conflicts become line-numbered warnings |
| A6 | import places classes by BFO ancestors and flags both straddle kinds |
| A7 | findings from any reasoner result, three-valued; asserted straddles suppressed only when the reasoner ran |
| A8 | an ontology is checked as given; anything else is compiled first |
| A9 | sidecar contract and exit codes |
| A10 | no em-dash in generated files |
| A11 | reference HermiT run finds the partition and within straddles |

**Module tests you add**

| Test | Pass condition |
|---|---|
| B1 | `POST /build` with `job-site-tracker.kw` and `Accept: application/zip` returns a zip with six files under `job-site-tracker/` |
| B2 | `POST /build` with the A2 source returns `422` and the same five diagnostics |
| B3 | `POST /check` with `straddle-imports-bfo.ttl` through OwlTester's pipeline returns `verdict {consistent: true, coherent: false}`, one partition and one within coherence finding, both with non-empty plain axioms |
| B4 | `POST /check` with `job-site-tracker.kindwork.json` returns `consistent: true, coherent: true` plus three findings from the interview (two chain, one partition) |
| B5 | A forced reasoner timeout returns `200` with an undetermined finding and `verdict {consistent: null, coherent: null}` |
| B6 | MCP `tools/list` shows the four tools; `kindwork_lint` on the A2 source returns `isError: true` with line 2 first |
| B7 | Every UI string, route reply, and doc in the module is free of U+2014 |
| B8 | A 9 MB body returns `413` |
| B9 | Import the B3 findings file into Kindwork: both cards link to their terms |

## 11. Out of scope

- BFO-Agent population. That is the BFO-Agent adapter in the ecosystem spec.
- Hosting generated trackers. A tracker is a file the client opens. See A4 below.
- Accounts, storage, and history.
- OWL functional syntax and OWL/XML input. These are refused with a message to re-save.

## ADJUDICATE

- **A1. Sidecar or port.** The sidecar keeps one source of truth at the cost of a Node dependency in OwlTester. A Python port removes Node but creates a second copy of every generator, and the copy will drift. Recommended: sidecar.
- **A2. Spawn per call or warm pool.** Spawning measured 100 to 130 ms per call, almost all Node startup. In-process the core costs about 2 ms, so a warm pool (2 workers holding the compiled script, line-delimited JSON) cuts calls to a few milliseconds. Start with spawning, and switch if p95 build latency matters.
- **A3. Calling the module from Kindwork.** The artifact cannot reach the server directly. Two routes:
  - Register `/kindwork/mcp` as a claude.ai custom connector, so Kindwork can call it through the artifact's connector capability. This bars public sharing of the Kindwork page.
  - Allow CORS from the artifact origin, if the platform permits it.
  Decide the auth model for the connector too: OAuth, or an authless endpoint behind a secret path.
- **A4. Tracker hosting.** Should OwlTester also serve built trackers at a URL per build? That needs storage, so it is out of scope until a client asks.
- **A5. IAO bridge or full IAO.** The bridge is one axiom and keeps the reasoner fast. Importing IAO in full catches more, but at the cost of load time. The bridge is enough for every keyword Kindwork emits.
- **A6. Disagreement policy.** Section 4 rule 5 marks HermiT/Pellet disagreement as undetermined. Confirm that this matches OwlTester's existing cross-check behavior.
- **A7. Example namespace.** Refuse to `build` when the namespace is still `https://example.org/...`, or warn? Proposed: warn on build, and refuse when the zip is requested for client delivery.
- **A8. Where it lives.** Mount on OwlTester's existing host, or on a subdomain such as `build.ontology.davidkoepsell.com`. This is cosmetic, but it affects the connector URL in A3.
