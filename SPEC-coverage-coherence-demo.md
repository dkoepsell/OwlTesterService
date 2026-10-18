# SPEC — Coverage Coherence Checker (live demo artifact)

**Status:** BUILT 2026-07-09 — see §10 for as-built deviations from the draft
**Target:** a single self-contained demo page on the existing OwlTesterService chassis, runnable live in front of Connor in under five minutes.
**Working title (on screen):** *Coverage Coherence Checker*

---

## 0. What this is and is not

The demo exists to make one contrast land: **a breadth-and-baseline coverage model gives two policy fragments the same score; a formalized-and-reasoned model tells them apart and proves why.** Everything on the page serves that contrast. Everything else — how the formalization works, the CLIF theory, the OWL axioms, the prover invocation — is deliberately invisible.

**Hard rules (enforced by this spec, not by presenter discipline):**

1. **Show the problem and the result, never the mechanism.** No axiom, no CLIF, no OWL syntax, no reasoner name is rendered anywhere on the demo page by default. The audience sees clauses, a structure diagram, a verdict, and a plain-English justification. A presenter-only `?debug=1` query param may expose the machinery for Q&A, but it is off by default and nothing on the page links to it.
2. **Their vocabulary, their lines.** All fixture text is realistic cyber / crime / management-liability / excess policy language. No BFO terms, no ontology jargon, no toy examples ("Animal subclassOf LivingThing") anywhere on the page.
3. **Nothing mocked is passed off as real.** The portfolio view is illustrative data and is labeled *"Illustrative portfolio — synthetic data"* on the chart itself. The coherence verdicts, by contrast, are genuinely computed by the reasoner stack — that is the point, and the presenter can say so truthfully.

Not in scope: NL→OWL extraction of arbitrary pasted policy text (that is the paid method), authentication, persistence of demo runs, portfolio computation over real books.

---

## 1. Demo narrative (the 5-minute run-of-show the page must support)

| Min | Beat | Screen state |
|-----|------|--------------|
| 0:00 | "Here are two cyber coverage fragments. Your model scores them." | **Panel 1**: Snippet A and Snippet B side by side, each with an identical baseline score badge (e.g. `Coverage presence: 94 / Baseline conformity: A-`). |
| 0:45 | "Same score. Now let's check whether the coverage they describe can actually exist." Click **Check coherence** (one button, checks both). | Both fragments run through the pipeline live (≤ 3 s each; precomputed fallback, §7). |
| 1:15 | Snippet A: **COHERENT** — "There is a claim scenario in which this carveback pays." Snippet B: **INCOHERENT** — "No possible claim can satisfy these three clauses at once." | **Panel 2**: verdict cards + clause-structure diagram per snippet, offending clauses in B highlighted, plain-English why beneath. |
| 2:30 | "Your model gave these the same number. Mine tells them apart — and here is exactly why." Walk the three highlighted clauses in B. | Same screen; presenter clicks each highlighted clause to pulse its node in the diagram. |
| 3:15 | "This isn't a one-off. It's one of four recurring structural failures." | **Panel 3**: taxonomy strip — four named failure-pattern cards. |
| 4:00 | "Rolled up across a book, it looks like this." | **Panel 4**: Contradiction Debt portfolio scatter (mocked, labeled), high-CD tail circled: *"the exception register — where litigation exposure concentrates."* |
| 4:45 | Close: bounded review offer. "Let me run this on a sample of your actual coverage objects." | No screen change needed. |

The page is a **single scrolling page with four sections**, revealed top-to-bottom (sections 2–4 hidden until the coherence check has run, so the reveal order matches the script). No multi-page navigation; the presenter never touches the URL bar.

---

## 2. Domain model — the coverage micro-ontology

A small, fixed insurance-coverage schema, authored once as Turtle in `fixtures/coverage/schema.ttl`. It is *not* shown to the audience; it exists to make grant/exclusion/carveback semantics reasoner-checkable.

### 2.1 Classes

| Class | Meaning |
|---|---|
| `cov:Claim` | A claim event (the individuals the reasoner quantifies over) |
| `cov:Loss` | A loss suffered by the insured |
| `cov:Policy`, `cov:Clause` | Document structure carriers (for the diagram, not for reasoning) |
| `cov:Grant`, `cov:Exclusion`, `cov:Carveback`, `cov:Definition` | Clause roles (subclasses of `cov:Clause`) |
| Per-fixture domain classes | e.g. `cov:NetworkSecurityEvent`, `cov:SocialEngineeringEvent`, `cov:EncryptedDataLoss`, `cov:MinimumSecurityMaintained` … defined per fixture |

### 2.2 The clause-semantics pattern

Each clause contributes a **class expression over `cov:Claim`**, built with the emitters already in `sool_owl_checks.py` (`intersection_of`, `union_of`, `complement_of`, `some_values_from`) — this is precisely what those emitters were written for; reuse them verbatim.

- **Grant G** ⇒ named class `cov:CoveredByG ≡ Claim ⊓ ⟨trigger expression⟩`
- **Exclusion E** ⇒ `cov:ExcludedByE ≡ Claim ⊓ ⟨exclusion trigger⟩`
- **Carveback C** (to exclusion E) ⇒ `cov:RestoredByC ≡ ExcludedByE ⊓ ⟨carveback condition⟩`
- **Definition D** ⇒ `EquivalentClasses` / `SubClassOf` axioms fixing the meaning of a defined term used by the others
- **Net covered position** ⇒ `cov:PayablePosition ≡ (CoveredByG ⊓ ¬ExcludedByE) ⊔ RestoredByC`

### 2.3 The check (what "coherent" means here)

For each fixture, the pipeline asks one question per *load-bearing class*, using the machinery that already exists:

- **Satisfiability of `RestoredByC`** (and of `PayablePosition`). If `RestoredByC` is unsatisfiable, the carveback restores nothing — the coverage it advertises is *illusory*. This is a `check_class_unsat` call in `prover9_runner.py`, unchanged.
- **Coherent verdict** = Mace4 finds a finite model containing a `RestoredByC` instance → rendered as *"There is a claim scenario in which this carveback pays."*
- **Incoherent verdict** = Prover9 proves `RestoredByC ⊑ ⊥` → the proof's used assumptions, mapped back to clause IDs (§4.3), become *"Clauses G1, E1 and C1 cannot all hold of any claim."*

Both directions come from the existing `cross_check` symmetry (Prover9 proof ↔ Mace4 model). No new reasoning code — only a thin adapter that builds the tiny theory from a fixture and labels the axioms.

---

## 3. Fixtures

All fixtures live in `fixtures/coverage/`, one JSON file per snippet plus the shared `schema.ttl`. **Fixtures are the demo.** The paste box (§5.1) is real but the rehearsed path uses these.

### 3.1 Fixture file format — `fixtures/coverage/<id>.json`

```json
{
  "id": "cyber-illusory-carveback",
  "title": "Cyber — Network Security Coverage, Endorsement 7",
  "line_of_business": "cyber",
  "failure_pattern": "illusory-carveback",        // or null for sound fixtures
  "baseline_score": { "presence": 94, "conformity": "A-", "components": [
      { "label": "Insuring agreement present", "hit": true },
      { "label": "Exclusion schedule complete", "hit": true },
      { "label": "Carveback present (market-standard)", "hit": true },
      { "label": "Defined terms present", "hit": true }
  ]},
  "clauses": [
    { "id": "G1", "role": "grant",     "heading": "Insuring Agreement A",
      "text": "We will pay Loss resulting from a Network Security Event first discovered during the Policy Period." },
    { "id": "E1", "role": "exclusion", "heading": "Exclusion 4(f)",
      "text": "This Policy does not apply to Loss arising out of the Insured's failure to maintain the Minimum Security Standards." },
    { "id": "C1", "role": "carveback", "heading": "Endorsement 7",
      "text": "Exclusion 4(f) shall not apply to Loss resulting from a Network Security Event occurring while the Insured maintained the Minimum Security Standards." },
    { "id": "D1", "role": "definition", "heading": "Definitions — Minimum Security Standards",
      "text": "\"Minimum Security Standards\" means the controls listed in Schedule B, maintained continuously." }
  ],
  "axioms": "cyber-illusory-carveback.ttl",       // clause-labeled axioms, sool emitters output
  "clause_axiom_map": { "G1": ["ax_g1"], "E1": ["ax_e1a","ax_e1b"], "C1": ["ax_c1"], "D1": ["ax_d1"] },
  "verdict_cache": "cyber-illusory-carveback.verdict.json",   // precomputed fallback, §7
  "plain_english_why": "Exclusion 4(f) only ever applies to claims where the Insured FAILED to maintain the Minimum Security Standards. Endorsement 7 restores coverage only for claims where the Insured MAINTAINED them — but those claims were never excluded in the first place. The set of claims Endorsement 7 gives back is empty: the carveback is illusory. The policy reads as if Endorsement 7 broadens coverage; it broadens nothing."
}
```

`plain_english_why` is hand-written per fixture. The reasoner supplies the *verdict* and the *minimal clause set*; the prose "why" is curated — this is honest (the clause set shown is exactly the proof's used assumptions) and avoids shipping raw proof text to a lay audience.

### 3.2 Required fixtures for the centerpiece (build these two first)

- **`cyber-sound`** — identical structure and near-identical wording to the above, but the carveback condition is *"…despite the Insured's compliance with the notification obligations in Section 9"* (a condition independent of the exclusion trigger). Mace4 finds a model; verdict COHERENT. **Its `baseline_score` block is byte-identical to the illusory fixture's** — that identity is the demo's first beat.
- **`cyber-illusory-carveback`** — as above. Prover9 proves `RestoredByC` empty; verdict INCOHERENT with `{G1, E1, C1}` highlighted.

The two snippets must be close enough in surface text that a human skimming them sees "same coverage, both look fine." Diff between them should be one clause condition.

### 3.3 Optional second live fixture (stretch, only if the centerpiece is done and rehearsed)

- **`crime-definitional-gutting`** — a crime/social-engineering grant whose defined term ("Computer Fraud") is narrowed by a definition until the grant class is unsatisfiable in the scenarios the insuring clause advertises. Same pipeline; demonstrates the taxonomy is real with a second live pattern.

The remaining two patterns (**same-term-two-meanings**, **follow-form contradiction**) are **taxonomy cards only** (§5.3) — named, one-sentence description, one-line realistic example each. Do not build fixtures for them for this demo.

---

## 4. Backend

### 4.1 New code — one blueprint, small

`coverage_demo.py` (repo root, Flask blueprint `coverage_demo`, registered in `app.py` with two lines; keep under 500 lines). No DB, no login, no writes to `uploads/`.

| Route | Method | Behavior |
|---|---|---|
| `/coverage` | GET | Renders `templates/coverage_demo.html` with the two centerpiece fixtures pre-loaded (clause text + baseline scores only; no verdicts yet). `?debug=1` adds the presenter-only machinery panel. |
| `/api/coverage/check/<fixture_id>` | POST | Runs the coherence pipeline (§4.2) for one fixture. Returns the verdict JSON (§4.4). |
| `/api/coverage/fixtures` | GET | Lists available fixtures (id, title, line of business) — feeds the paste-box preset dropdown. |

### 4.2 Pipeline per check (all existing machinery)

1. Load `schema.ttl` + fixture `axioms` TTL into an isolated owlready2 `World` (reuse the per-load isolation pattern from the BVSS fix, commit `1fad406`).
2. Translate to the Prover9 assumption list via the existing OWL→FOL path (`fol_export.py` / `clif_theory.py` — whichever `cross_check` already consumes; **do not build a new translator**).
3. `check_class_unsat(assumptions, "RestoredByC", ...)` and `check_class_unsat(assumptions, "PayablePosition", ...)` with the existing 5 s timeout.
4. Map each returned proof's used assumptions → axiom labels → clause IDs via `clause_axiom_map`. The minimal contradicting clause set is `{clauses whose axioms appear in the proof}`.
5. Assemble verdict JSON; on any failure or timeout, serve `verdict_cache` instead (§7).

Theories here are tiny (≤ ~20 axioms); Prover9/Mace4 will return in well under a second. The 3 s UI budget is generous.

### 4.3 Axiom labeling

Author the fixture TTL with one `rdfs:label`-style annotation per axiom-carrying construct (or generate the TTL with a small script using `sool_owl_checks` emitters, tagging each emitted axiom `ax_g1`, `ax_e1a`, …). The adapter must carry these labels through to the Prover9 assumption lines (Prover9 supports `# label(ax_g1)` on formulas — use it, so the proof's used-clause list is directly mappable). If the existing exporter drops labels, maintain a positional side-table in the adapter instead; either is fine, but the mapping must be exact, because the highlighted clauses ARE the demo's credibility.

### 4.4 Verdict JSON (also the `verdict_cache` file format)

```json
{
  "fixture_id": "cyber-illusory-carveback",
  "coherent": false,
  "headline": "No possible claim can satisfy these three clauses at once.",
  "checked_positions": [
    { "position": "carveback_restores", "label": "Does Endorsement 7 restore any coverage?",
      "result": "empty", "contradicting_clauses": ["G1", "E1", "C1"] }
  ],
  "plain_english_why": "…(from fixture)…",
  "scenario": null,                      // for coherent verdicts: a one-sentence witness, see below
  "computed_live": true                  // false when served from cache — shown only in ?debug=1
}
```

For **coherent** verdicts, `scenario` is a one-sentence rendering of the Mace4 witness in claim terms, hand-templated per fixture (e.g. *"Example: a ransomware event in March, Schedule B controls in place, notified within 30 days — Endorsement 7 pays."*). Template lives in the fixture file; the pipeline only fills it in when Mace4 actually finds a model.

---

## 5. Frontend — `templates/coverage_demo.html` + `static/js/coverage-demo.js`

Extends `layout.html` but hides the app's global nav chrome (this page will be projected; it should look like a product, not the OwlTester dev tool). Bootstrap 5 dark theme as everywhere else. **No D3 force layout** — follow the navigation-first discipline of the rebuilt BVSS explorer, and reuse its visual language (node/ring styling from `bvss_fixed.html` / `ontology-visualizer.css`) for the clause-structure diagram.

### 5.1 Panel 1 — the two snippets, same score

- Two cards side by side: fixture title, the four clauses as styled document text (role chip on each clause: GRANT / EXCLUSION / CARVEBACK / DEFINITION), and a **baseline score badge** rendered identically on both, with the checklist components on hover/expand: every box ticked on both.
- Small caption under the badges: *"Baseline scoring: breadth-and-presence model (illustrative)."* — honest about the mock without deflating it.
- A collapsed "paste your own" box with a fixture-preset dropdown. Pasting free text shows: *"Free-text intake is part of the full review — this demo runs on pre-formalized fragments."* (True, and it protects rule #1.) Selecting a preset loads that fixture into a card.
- One primary button: **Check coherence** (checks both cards; disabled after run).

### 5.2 Panel 2 — verdicts + structure (revealed after check)

Per card:

- **Verdict banner**: green `COHERENT — a claim scenario exists in which this coverage pays` (with the witness sentence) / red `INCOHERENT — no possible claim satisfies these clauses` (with the headline).
- **Clause-structure diagram**: a small static SVG graph — Grant, Exclusion, Carveback, Definition nodes laid out in a fixed diamond (4–6 nodes; hand-positioned per role, no physics), edges labeled *limits*, *restores from*, *defines term in*. In the incoherent card, the `contradicting_clauses` nodes and their edges pulse red; elsewhere neutral. Clicking a clause in the document card pulses its node and vice-versa (the presenter's 2:30 beat).
- **Plain-English why** beneath the diagram, with the clause IDs in the prose rendered as the same colored chips.
- Nothing else. No proof text, no axiom count, no reasoner name. (`?debug=1` appends a collapsed panel with the raw verdict JSON, the Prover9 proof, and timing — presenter-only.)

### 5.3 Panel 3 — the taxonomy strip

Four cards in a row, each: pattern name, one sentence, one-line realistic example, and a line-of-business tag. The two live ones get a `✓ shown live` marker; the other two get `found in bounded review`.

1. **Illusory carveback** — the carveback's condition contradicts the exclusion it modifies; it restores nothing.
2. **Definitional gutting** — a defined term is narrowed until the grant that uses it can no longer pay the scenarios it advertises.
3. **Same term, two meanings** — one term used with incompatible senses in two clauses; which sense applies decides the claim.
4. **Follow-form contradiction** — an excess/follow-form layer incorporates underlying terms that contradict its own endorsements.

Footer line: *"A bounded review finds which of these live in your book."*

### 5.4 Panel 4 — portfolio Contradiction Debt (mocked)

- One scatter: X = policy count percentile / policy id bucket, Y = **Contradiction Debt** score; ~200 synthetic points, a long low band and a small high tail; the tail circled with the annotation *"the exception register — litigation exposure concentrates here."*
- Chart title includes the label **"Illustrative portfolio — synthetic data"** (rule #3; on the chart image itself, not just nearby text).
- Static data generated once and checked in as `fixtures/coverage/portfolio_mock.json` — not generated at runtime (determinism for rehearsal). Rendered with a small inline SVG/canvas plot in `coverage-demo.js`; do not add a charting library. Follow the dataviz skill when building this chart.

---

## 6. Reuse map (build almost nothing)

| Need | Reused component | New work |
|---|---|---|
| Class-expression construction for fixtures | `sool_owl_checks.py` emitters | fixture-authoring script (scratch, or `scripts/`) |
| Unsat check + proof | `prover9_runner.check_class_unsat` / `cross_check` | axiom-label passthrough (§4.3) |
| Model witness for coherent side | Mace4 path in `prover9_runner` | witness→sentence template fill |
| OWL→Prover9 theory | existing `fol_export.py` / `clif_theory.py` path | thin adapter in `coverage_demo.py` |
| Isolated ontology load | owlready2 per-load `World` pattern (BVSS fix) | none |
| Diagram visual language | BVSS explorer styles (`ontology-visualizer.css`) | small fixed-layout SVG renderer |
| Page chrome | `layout.html`, Bootstrap dark | `coverage_demo.html` |

New files: `coverage_demo.py`, `templates/coverage_demo.html`, `static/js/coverage-demo.js`, `fixtures/coverage/*` (schema, 2–3 fixtures, verdict caches, portfolio mock), plus a fixture-authoring script. No model/DB changes, no migrations.

---

## 7. Reliability — the demo must not die on stage

- **Precomputed verdict caches** (`*.verdict.json`) are generated at fixture-authoring time and checked in. The API serves the cache whenever the live pipeline errors or exceeds 3 s. The UI is identical either way; `computed_live` is visible only under `?debug=1`. The presenter can honestly say the verdicts are reasoner-produced — the caches *were* produced by the reasoner.
- **Prover9/Mace4 availability check at page load**: `/coverage` pings `prover9_available()`; if missing (laptop demo without the built binaries), everything silently runs cache-only.
- The page makes **no OpenAI calls** and needs no API keys, no DB, no login. It must work on `localhost` with nothing but the repo + Python deps (+ optionally the prover binaries).
- Rehearsal checklist ships in the PR description: cold-start the app, run the full 5-minute script twice, once with binaries and once with them renamed away (cache path).

## 8. Acceptance criteria

1. `GET /coverage` renders both centerpiece fixtures with **byte-identical baseline score badges** and no verdicts.
2. **Check coherence** returns within 3 s per fixture; `cyber-sound` → COHERENT with witness sentence; `cyber-illusory-carveback` → INCOHERENT with exactly `{G1, E1, C1}` highlighted in both the document card and the diagram.
3. The highlighted clause set is derived from the Prover9 proof's used assumptions (verified in a unit test against the fixture theory), not hard-coded in the UI path. (The cache file may store it, but the cache is itself proof-derived.)
4. No OWL/CLIF/FOL syntax, axiom text, or reasoner name appears anywhere without `?debug=1`.
5. Taxonomy panel shows the four named patterns; portfolio panel renders the labeled synthetic scatter.
6. Full page works with prover binaries absent (cache path) and with no network access.
7. Tests: fixture-theory unsat/sat round-trip (both fixtures), clause-mapping exactness, cache-fallback path, and a `GET /coverage` smoke test. Add under `tests/`.

## 9. Build order

1. Fixtures first: author `schema.ttl` + both centerpiece TTLs with the emitter script; verify by hand with `prover9_runner` that A is sat (Mace4 model) and B's `RestoredByC` is unsat with the intended three-clause core. **This is the risk item — if the contradiction core comes back with the wrong clause set, fix the axioms before touching any UI.**
2. Adapter + API route + verdict caches + tests.
3. Page: Panel 1 → Panel 2 (verdicts + diagram) → Panels 3–4.
4. Rehearse the 5-minute script against the real page; tune wording of headlines/why-prose from how it lands out loud.
5. Stretch only after rehearsal: `crime-definitional-gutting` as a third preset.

---

## 10. As built (2026-07-09) — deviations from the draft above

Shipped: `coverage_demo.py` (blueprint, mounted best-effort in `app.py`),
`templates/coverage_demo.html` (standalone dark page, no app nav),
`static/js/coverage-demo.js`, `fixtures/coverage/` (2 fixtures + prover-produced
verdict caches + `portfolio_mock.json`), `tests/test_coverage_demo.py` (12 tests),
plus two generic additions to `prover9_runner.py`: `prove_goal()` (returns the
proof's used labels) and `find_model()`.

Deviations, each found during build:

1. **No `schema.ttl`, no OWL→FOL translation.** `fol_export.build_theory` only
   handles named subsumption/disjointness — it cannot express the carveback's
   boolean class expressions. Fixture axioms are therefore authored directly as
   clause-labeled Prover9 formulas in the fixture JSON (`axioms: [{label,
   clause_id, formula}]`), and `build_assumptions()` assembles the block with
   `# label(...)` attributes. Tiny purpose-built theories; exact clause mapping
   for free. The `sool_owl_checks` emitters were not needed.
2. **The contradiction core is {E1, C1, D1}, not {G1, E1, C1}** (§8.2 amended).
   Worked through formally, the grant is not load-bearing for the illusory
   carveback: the minimal unsat core is exclusion + carveback + the definition
   whose "maintained continuously" makes maintaining/failing mutually exclusive.
   Verified live: Prover9's proof uses exactly `ax_c1, ax_d1, ax_e1`.
3. **`check_class_unsat` was not reusable as-is** — it returns only a status
   string, no proof. Hence `prove_goal`/`find_model` in `prover9_runner.py`;
   `cross_check` untouched.
4. **Mechanism-stripping is enforced server-side**: the page embeds only a
   public fixture view (id/title/lob/score/clauses — no axioms), and the
   non-debug API drops the `debug` block and internal position names. The smoke
   test greps the served page for prover names/axiom text (§8.4 is a test).
5. Mace4 runs **only** on Prover9's no-proof side — it does not terminate on
   unsatisfiable input (confirmed empirically during fixture verification).

Verified: fixture round-trip live (sound → Mace4 model + witness; illusory →
proof, core E1/C1/D1, ~3 ms), cache fallback with engines absent, page + API
smoke, full prover-related suite green. Not yet done: on-stage rehearsal (§9.4)
and no screenshot check (no headless browser on the dev box) — eyeball the page
once before presenting.

**Stretch fixture shipped (same day):** `crime-definitional-gutting` — the
grant's Fraudulent Instruction extension requires (via D2) constituting
Computer Fraud, which (via D1) requires a transfer no Employee initiated;
core {G1, D1, D2}, with G1 carrying two axioms to exercise the multi-axiom
clause mapping. Fixtures may now declare explicit diagram `edges` and per-clause
`pos` (needed when a role occurs twice); role-based defaults still cover the
cyber pair. The page renders all fixtures, centerpiece pair first; the
definitional-gutting taxonomy card is marked "shown live".

---

## 11. Generalization path — from demo to OwlTesterService feature

The demo hard-codes one domain. What it actually demonstrates is a general
capability the main service does not yet have: **named satisfiability probes
with proof-derived justification cores mapped back to human-meaningful source
units.** The path from one to the other is four phases, each independently
shippable and each reusing the previous.

### Phase 1 — labeled axioms and proof cores in the existing analysis pipeline

The foundation, and the direct lift of the demo's core mechanic.

- Extend `fol_export.py` to attach `# label(ax_<n>)` attributes to every emitted
  formula and return a side-table `label → {source axiom, entity IRIs, rendered
  form}`. (The demo bypassed this by authoring labeled formulas directly; the
  service must generate them from OWL.)
- Where the auto-run `cross_check` (commit `7ec6535`) finds an unsatisfiable
  class, re-run `prove_goal` (already in `prover9_runner.py`) to get the used
  labels, and store the core in `OntologyAnalysis` (new JSON column, migration
  per house style).
- Surface in `analysis.html` and `report.html`: "these N axioms cannot all
  hold", rendered as the original axioms, not FOL. This is the demo's verdict
  card with axioms in place of clauses.

Small–medium effort. Generic value immediately: every ontology user gets
minimal-core explanations instead of a bare "unsatisfiable".

> **SHIPPED 2026-07-09.** `render_prover9(labels=True)` + `axiom_table()` in
> `fol_export.py` (download exports unchanged — labels are opt-in);
> `_extract_proof_cores()` in `prover9_runner.py` re-proves each unsatisfiable
> class (capped at 10) over the labeled export and stores
> `proof_cores` inside the existing `prover_cross_check` JSON — **no
> migration**. Rendered on the analysis page (server-side block + the JS
> poller) and in report.html §8 as "these N axioms cannot all hold", with BFO
> category axioms badged and a caveat when a background theory participates.
> Verified end-to-end on `quality_disposition_straddle.owl`: Force's core is
> exactly {Force ⊑ quality, Force ⊑ disposition, disposition ⊥ quality [BFO]}.
> Tests in `tests/test_proof_cores.py`.

### Phase 2 — user-declared satisfiability probes ("checked positions")

Generalize the demo's one-button check into an analysis-page feature: pick any
class (or enter a simple class expression) and ask *"can this class have any
instance?"* → COHERENT with a Mace4 witness, or EMPTY with the Phase-1 core.

- `POST /api/analysis/<id>/probe` running the demo's exact
  `prove_goal`/`find_model` ordering (Prover9 first; Mace4 never on unsat).
- Witness rendering cannot use hand-written sentences for arbitrary ontologies:
  render the Mace4 model as a small instance diagram instead (BVSS visual
  language — the explorer already draws individuals).
- Extract the demo's verdict card into a shared template partial + JS module so
  the demo page and the analysis page render verdicts identically.

Medium effort. Depends on Phase 1's label side-table.

> **SHIPPED 2026-07-09** (named classes; class-expression input deferred to a
> follow-up). `probe_class()` in `prover9_runner.py` — Prover9-first ordering,
> Phase-1 core on EMPTY; on COHERENT the Mace4 interpretation is decoded
> (`_parse_interpretation` / `_witness_from_model`) into the witness
> individual's class memberships, rendered as "an individual that instantiates
> X, Y, Z" rather than a full instance diagram (the diagram remains open).
> `POST /api/analysis/<id>/probe` resolves the target by IRI, FOL symbol, or
> label and runs synchronously; nothing is stored. Probe panel on the analysis
> page under the cross-check card. Tests in `tests/test_probe.py`; suite-wide
> scratch DATABASE_URL moved into tests/conftest.py so app-importing test
> files can no longer poison each other's database binding.

### Phase 3 — coherence profiles (the productized typology)

The insurance overlay, data-ized. A **profile** is a JSON bundle:

- a role vocabulary and how ontologies declare it (an annotation property —
  e.g. `cov:role = grant|exclusion|carveback|definition`, or BFO-native roles);
- **position templates** that expand mechanically over the role structure: "for
  every carveback C restoring from exclusion E, probe C's restored class";
  "for every definition D used by grant G, probe G's advertised class";
- named findings (the four failure patterns are the insurance profile's
  finding set) with prose templates;
- diagram layout hints (the demo's `pos`/`edges` fields, generalized).

The engine is a profile interpreter: expand templates → run Phase-2 probes →
emit named findings into the `owltester/` pipeline as a new stage, feeding the
BVSS explorer's findings rings and a report section. **Profiles as data keeps
the method boundary**: the interpreter is generic and shippable; the insurance
profile (and future deontic/regulatory or BFO-pattern profiles) can stay
private, per-client, and priced. The sandbox builder is the authoring surface:
add role annotations there and "check coherence" becomes a button on any
sandbox ontology — also how new demo fixtures get built without hand-writing
FOL.

Large effort; this is the product. Depends on Phases 1–2.

### Phase 4 — real Contradiction Debt (the portfolio panel, un-mocked)

Define CD as a weighted count of empty load-bearing positions (weights from the
profile's position importance), computed per file. Batch-run over a user's
uploaded files (`OntologyFile` history already exists), and replace the demo's
synthetic scatter with a dashboard: real distribution, the exception register as
a sorted drill-down list linking each high-CD file to its named findings.

Medium effort once 1–3 exist. This is the "bounded review" deliverable as a
screen.

### What stays out, permanently

Free-text/NL intake of policy or ontology prose. The service consumes formal
artifacts (OWL/CLIF/sandbox structures); formalization of natural-language
documents remains the paid method, exactly as the demo's paste box says.
