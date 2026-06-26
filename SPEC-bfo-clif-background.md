# Scope: Full BFO-2020 CLIF theory as prover background

**Status:** proposed follow-up (not yet implemented)
**Depends on:** the Prover9/CLIF export + cross-check already shipped (`fol_export.py`,
`prover9_runner.py`, `bfo/bfo-2020.clif`).
**Goal:** let the prover cross-check use the *complete* first-order BFO-2020 axiomatization
as background theory, so it can confirm or refute entailments that are mediated by BFO
relations and restrictions, not just raw subclass/disjointness straddles.

Do not introduce em-dashes into user-facing copy, docstrings, or report templates.

---

## 1. Why

What ships today derives BFO disjointness from the OWL catalog and emits only the
subsumption and disjointness axioms the ontology references. That is enough to rediscover
partition straddles (a class under two disjoint BFO categories, e.g. `Force` under Quality
and Disposition). It is **not** enough to check entailments that depend on BFO's relational
axioms: domains/ranges of `inheres_in`, `participates_in`, `has_role`; the mereology of
`part_of`; the continuant/occurrent bridging axioms. Those live in the official BFO-2020
CLIF theory (now vendored at `bfo/bfo-2020.clif`, 13 normative modules), which the prover
does not currently see.

Loading the full BFO FOL theory as background turns the cross-check from "agrees on
straddles" into "agrees on everything BFO entails", which is the real point of a FOL-BFO-OWL
tester.

## 2. The core problem: CLIF is not Prover9

The vendored theory is ISO Common Logic (s-expressions). Prover9 reads LADR. We need a
faithful CLIF -> Prover9 translation. Subtleties:

- **Vocabulary alignment.** BFO CLIF uses relation/predicate names like `instance-of`,
  `continuant-part-of-at-all-times`, `exists-at`, `temporal-part-of`. The export uses
  `instance_of` / `instance_of_at`. The translator must map BFO CLIF predicate symbols onto
  the export's signature (or vice versa) so the two theories talk about the same predicates.
  This mapping is the crux; get it wrong and nothing connects.
- **Temporalization mismatch.** BFO 2020 CLIF temporalizes instantiation and relations with
  explicit time arguments and quantifies over temporal regions. The export already encodes
  continuant = ternary, occurrent = binary; the BFO theory's arities must be reconciled with
  that convention, or the convention must be replaced wholesale by BFO's own.
- **Sorts and sequence markers.** Common Logic has sequence markers and an untyped domain;
  BFO CLIF uses guard predicates rather than sorts. Prover9 is untyped first-order, so this
  is tractable, but any CL feature beyond plain FOL (sequence markers `...`, functional terms
  used as predicates) must be rejected or rewritten.
- **Modularity.** BFO CLIF is 13 `(cl-text ...)` modules with imports, not one flat theory.
  The translator must concatenate the modules into a single assumptions set.

## 3. Proposed approach

Reuse the s-expression reader already written for input parsing (`fol_input._SExprParser`)
rather than writing a new one.

1. **CLIF -> internal -> Prover9.** Extend `fol_input` (or a new `clif_theory.py`) to parse
   each `(cl-text ...)` module into the internal infix AST, then render to Prover9 with the
   existing renderer machinery in `fol_export`. Most of the connective handling already
   exists; the new work is predicate-symbol mapping and arity reconciliation.
2. **Signature map.** A small, reviewed, hand-authored table mapping BFO CLIF predicates to
   the export signature (e.g. CLIF `(instance-of x C t)` -> `instance_of(x,C,t)`). Keep it in
   `bfo/` next to the catalog so the sibling `bfo-agent` repo can reuse it. This table is the
   single source of truth and must be unit tested against the vendored CLIF.
3. **Background assembly.** `prover9_runner` gains an optional `background_p9` argument: the
   translated BFO theory, prepended to the per-class goal input. Cache the translation once
   per process (it is large and static).
4. **Opt-in flag.** Running with the full BFO background is much slower (hundreds of axioms,
   so Prover9 search blows up). Make it opt-in per cross-check run (a checkbox on the panel,
   `?bfo_background=1` on the endpoint), defaulting off. Keep the lightweight derived-disjointness
   cross-check as the default.
5. **Resource bounds.** With the full theory, set conservative Prover9 limits
   (`assign(max_seconds, ...)`, `assign(max_megs, ...)`) per class, and surface "undetermined"
   distinctly from "satisfiable" when the prover times out. Never silently treat a timeout as
   agreement.

## 4. Acceptance

- A unit test translates the vendored `bfo/bfo-2020.clif` to Prover9 with zero unmapped
  predicate symbols (the signature map covers everything the theory uses), and the result
  parses as valid Prover9 input (Mace4 finds a small model of the background alone, proving it
  is consistent and was not mistranslated into a contradiction).
- With the BFO background on, a fixture that is coherent only because of a relation axiom
  (e.g. `q inheres_in p` where `q` is a quality and `p` a process, which BFO's `inheres_in`
  range forbids) is flagged unsatisfiable by the prover, and the panel attributes it to the
  BFO background.
- With the background off, behavior is byte-for-byte unchanged from today.
- The cross-check reports timeouts as "undetermined", never as agreement.

## 5. Effort and risk

- **Effort:** medium to large. The translator and signature map are the bulk; the runner and
  UI changes are small. Plan for iteration on the signature map against real BFO axioms.
- **Risk:** Prover9 performance on the full theory is the main risk. First-order BFO is a big,
  highly connected theory and Prover9 may not terminate per class within a sane budget. Mace4
  (model finding) may be the more practical engine for satisfiability of individual classes.
  Mitigate with strict per-class limits, the opt-in flag, and honest "undetermined" reporting.
- **Alternative considered:** ship the BFO theory to a CLIF-native reasoner instead of
  translating to Prover9. Rejected for now because it adds a second prover dependency and the
  whole point is to cross-check against an *independent* FOL engine we already run.

## 6. Out of scope

- Generating ontologies or fixing them (that is the `bfo-agent` repo).
- Translating arbitrary user CLIF theories beyond the BFO background and the single-expression
  tester input that already works.
