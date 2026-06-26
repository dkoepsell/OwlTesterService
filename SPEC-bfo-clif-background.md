# Scope: Full BFO-2020 CLIF theory as prover background

**Status:** scoped, not yet implemented. Picking up next week.
**Depends on:** the Prover9/CLIF export + cross-check already shipped in v2.0
(`fol_export.py`, `prover9_runner.py`, `fol_input.py`, `bfo/bfo-2020.clif`).
**Goal:** let the prover cross-check use the *complete* first-order BFO-2020
axiomatization as background theory, so it can confirm or refute entailments that
are mediated by BFO relations and restrictions, not just raw subclass/disjointness
straddles.

Do not introduce em-dashes into user-facing copy, docstrings, or report templates.

---

## 1. Why

What ships today derives BFO disjointness from the OWL catalog and emits only the
subsumption and disjointness axioms the ontology references. That is enough to
rediscover partition straddles (a class under two disjoint BFO categories, e.g.
`Force` under Quality and Disposition). It is **not** enough to check entailments
that depend on BFO's relational axioms: domains/ranges of `inheres-in`,
`participates-in`, `has-role`; the mereology of `continuant-part-of`; the
continuant/occurrent bridging axioms. Those live in the official BFO-2020 CLIF
theory (vendored at `bfo/bfo-2020.clif`, 13 normative modules), which the prover
does not currently see.

Loading the full BFO FOL theory as background turns the cross-check from "agrees
on straddles" into "agrees on what BFO entails", which is the real point of a
FOL-BFO-OWL tester. The divergence already observed on analysis 2782 (OWL reasoner
found 52 unsatisfiable classes, prover found 0) is exactly this gap: those classes
are unsatisfiable through restriction- and relation-mediated reasoning the current
lightweight export cannot express.

## 2. What is actually in the vendored CLIF (measured)

Parsed `bfo/bfo-2020.clif` (13 `cl:text` modules, ISO/IEC 24707 `cl:` dialect):

- Logical operators present: `forall` (350), `exists` (274), `if` (326),
  `and` (301), `not` (697), `or` (46), `iff` (60). Plain names, no `cl:` prefix.
- CL wrappers to handle: `cl:text`, `cl:ttl` (titling, 2nd arg is a URL string),
  `cl:comment` (annotation string, optionally wrapping the real axiom as its last
  element), `cl:outdiscourse` (vocabulary declaration, not an axiom), `cl:imports`.
- **Core BFO predicates and their arities** (the signature map must cover all of
  these; ternary = time-indexed continuant relation, binary = occurrent/temporal):
  - Type guards (arity 1): `universal`, `particular`, `entity`.
  - Instantiation (arity 3): `instance-of` (x, type, t). 550 uses.
  - Continuant relations (arity 3): `continuant-part-of`, `has-continuant-part`,
    `proper-continuant-part-of`, `has-proper-continuant-part`, `member-part-of`,
    `has-member-part`, `participates-in`, `has-participant`, `located-in`,
    `location-of`, `occupies-spatial-region`, `spatially-projects-onto`,
    `generically-depends-on`, `concretizes`, `is-concretized-by`,
    `has-material-basis`, `material-basis-of`, `is-carrier-of`.
  - Occurrent / temporal relations (arity 2): `temporal-part-of`,
    `proper-temporal-part-of`, `has-temporal-part`, `has-proper-temporal-part`,
    `occurrent-part-of`, `proper-occurrent-part-of`, `has-occurrent-part`,
    `has-proper-occurrent-part`, `precedes`, `preceded-by`, `occurs-in`,
    `environs`, `history-of`, `has-history`, `occupies-temporal-region`,
    `occupies-spatiotemporal-region`, `temporally-projects-onto`,
    `has-first-instant`, `first-instant-of`, `has-last-instant`,
    `last-instant-of`, `exists-at`.
  - Dependence / realizable (arity 2): `specifically-depends-on`,
    `specifically-depended-on-by`, `inheres-in`, `bearer-of`, `realizes`,
    `has-realization`.

> Finding: the existing `fol_input._SExprParser` is a *bare* s-expression reader.
> It does not understand CLIF single-quoted string literals, so the prose inside
> `cl:comment 'role is a universal [ewm-1]'` is tokenized into spurious atoms
> (`ISO/IEC`, `CLIF`, `cl:`, `s,c`, `both`, `at`, `source`, ...). A string-aware
> tokenizer is therefore a **prerequisite** (Phase 1), not an afterthought. The
> bare reader is fine for the small tester inputs it handles today; it is not
> sufficient for the comment-heavy BFO file.

## 3. The core problem: CLIF is not Prover9

The vendored theory is ISO Common Logic. Prover9 reads LADR. We need a faithful
CLIF -> Prover9 translation. Subtleties:

- **Vocabulary alignment.** Map every BFO CLIF predicate (Section 2) onto the
  export's signature. The export uses `instance_of(x,C,t)` for continuants and
  `instance_of_at(x,O)` for occurrents; BFO CLIF uses `instance-of(x,type,t)`
  uniformly (arity 3). Decide one canonical signature. Likely simplest: adopt
  BFO's own `instance-of/3` everywhere for the background, and translate the
  *ontology export* into the same convention when the background is enabled, so
  both theories share one predicate set. This avoids a lossy continuant/occurrent
  re-encoding and is the cleanest path to "they talk about the same predicates".
- **Hyphen to underscore.** Prover9 identifiers cannot contain hyphens. Rewrite
  `continuant-part-of` -> `continuant_part_of`, etc. Deterministic and total.
- **Sorts and sequence markers.** CL has an untyped domain; BFO uses guard
  predicates (`universal`, `particular`, `entity`) rather than sorts. Prover9 is
  untyped first-order, so guards translate directly as unary predicates. Reject or
  log any CL feature beyond plain FOL (sequence markers, functional terms used as
  predicates); the measured vocabulary shows none are used, so this is a guard.
- **Modularity.** 13 `cl:text` modules with `cl:imports`. Concatenate them into a
  single `formulas(assumptions).` block; ignore `cl:imports`/`cl:ttl`/`cl:comment`
  wrappers, keep only their axiom payloads.

## 4. Phased plan

Each phase is independently shippable and testable.

**Phase 0 (done): measurement.** This document; the vocabulary inventory above.

**Phase 1: CLIF string-aware tokenizer.** Upgrade `fol_input._SExprParser` (or add
`clif_lexer.py`) to recognize CLIF single-quoted string literals and `cl:`-prefixed
operators, so `cl:comment` prose is one token and never leaks into the axiom set.
- Acceptance: re-running the Section 2 extractor yields only the real BFO
  predicates (zero noise atoms like `ISO/IEC`, `cl:`, `both`).

**Phase 2: signature map.** Add `bfo/clif_signature.py` (or `.json`): a reviewed
table mapping each BFO CLIF predicate to a Prover9 symbol + arity, plus the
hyphen->underscore rule and the logical-operator map. Keep it in `bfo/` so the
sibling `bfo-agent` repo can reuse it.
- Acceptance: a unit test asserts the map covers every predicate the tokenizer
  finds in `bfo/bfo-2020.clif` (zero unmapped symbols), and flags any new symbol a
  future BFO bump introduces.

**Phase 3: CLIF -> Prover9 translator.** `clif_theory.py`: walk the tokenized
modules, strip wrappers, render axioms to Prover9 via the signature map, reusing
`fol_export`'s connective rendering. Emit one assumptions block.
- Acceptance: output parses as valid Prover9; Mace4 finds a small model of the
  background **alone** (proves it is consistent and was not mistranslated into a
  contradiction). Cache the translation once per process.

**Phase 4: align the ontology export.** When the background is enabled, render the
ontology's own axioms in the *same* signature as the background (BFO `instance-of/3`
convention), so goals and background share predicates. Without the flag, the
current export is unchanged.
- Acceptance: with background off, output is byte-for-byte identical to today.

**Phase 5: wire into the cross-check.** `prover9_runner.cross_check` gains an
opt-in `bfo_background=True` path: prepend the cached translated theory, set
conservative per-class limits (`assign(max_seconds,...)`, `assign(max_megs,...)`),
and report `undetermined` distinctly from `satisfiable` on timeout.
- Acceptance: a fixture coherent only via a relation axiom (e.g. `q inheres-in p`
  with `q` a quality and `p` a process, which BFO's `inheres-in` signature forbids)
  is flagged unsatisfiable with the background on, and the panel attributes it to
  "BFO background". Timeouts never read as agreement.

**Phase 6: UI + endpoint.** Checkbox on the analysis FOL panel and
`?bfo_background=1` on `POST /api/analysis/<id>/prover-check`; default off. Verdict
copy distinguishes "agree (with BFO background)" from the lightweight check.

## 5. Test plan

- Tokenizer: golden test on `bfo/bfo-2020.clif` predicate set (Phase 1).
- Signature map completeness against the live tokenizer output (Phase 2).
- Background self-consistency via Mace4 (Phase 3).
- Export byte-identity with flag off (Phase 4).
- Relation-mediated unsatisfiability fixture, plus a timeout-reports-undetermined
  test (Phase 5).
- All existing tests stay green; the default cross-check path is untouched.

## 6. Effort and risk

- **Effort:** medium to large. Phases 1 to 3 (tokenizer, map, translator) are the
  bulk; 4 to 6 are small. Budget real iteration on the signature map.
- **Risk:** Prover9 performance on the full theory. First-order BFO is large and
  highly connected; Prover9 may not terminate per class within a sane budget.
  Mace4 (model finding) is likely the more practical engine for per-class
  satisfiability. Mitigate with strict per-class limits, the opt-in flag, and
  honest "undetermined" reporting. This is why the lightweight derived-disjointness
  check stays the default.
- **Alternative considered:** ship the BFO theory to a CLIF-native reasoner instead
  of translating to Prover9. Rejected: it adds a second prover dependency and the
  whole point is to cross-check against an *independent* FOL engine we already run.

## 7. Out of scope

- Generating or fixing ontologies (that is the `bfo-agent` repo).
- Translating arbitrary user CLIF theories beyond the BFO background and the
  single-expression tester input that already works.

## 8. Next-week pickup

Start at **Phase 1** (the string-aware tokenizer): it is the unblocking
prerequisite and is fully specified and independently testable. The Section 2
extractor script (parse `bfo/bfo-2020.clif`, walk wrappers, count predicate atoms)
is the ready-made acceptance harness: when it reports only real BFO predicates,
Phase 1 is done.
