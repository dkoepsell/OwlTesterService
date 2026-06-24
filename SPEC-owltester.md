# Build Spec: FOL-BFO-OWL Tester Hardening

**Target repo:** `FOL-BFO-OWL-tester` (dkoepsell)
**Role of this service:** post-hoc audit. It consumes an OWL file and reports consistency, classification, and a FOL export. It does **not** generate ontologies. Generation-side fixes live in the separate `bfo-agent` spec.
**Goal:** turn the tester from an is-a-tree displayer into a BFO-aware coherence checker that names what is broken and proves it.

---

## 0. Assumptions and how to adapt

I do not have the repo's exact layout in front of me. Before writing code, inspect and record:

- Language and web framework (the rendered report implies a Python web service, likely Flask; confirm).
- How the reasoner is invoked. The report cites **Pellet** and shows a `reasoner_skipped` path, so there is an existing OWL-reasoning entry point. Find it and treat it as the integration seam.
- The OWL-handling library. If it is `owlready2`, the examples below apply directly. If it is the OWLAPI via Java/py4j, keep the same task boundaries and translate calls.

If any assumption here is wrong, **stop and report the mismatch before proceeding** rather than guessing. State assumptions you make in code comments.

Do not introduce em-dashes into any user-facing copy, docstrings, or report templates in this project.

---

## 1. Import full BFO instead of bare IRIs

**Problem.** BFO categories appear only as label-less IRIs (`BFO_0000019`, `BFO_0000040`, ...) carrying a hand-copied fragment of seven `DisjointWith` pairs. The picklist of available categories cannot be populated and the disjointness structure is incomplete.

**Task.**
1. Vendor the **BFO 2020 OWL release** (ISO/IEC 21838-2) into the repo at `bfo/bfo-2020.owl`. Pin the version; record the release tag in `bfo/VERSION`.
2. At analysis time, load the user ontology **with BFO as an import** (in owlready2, load `bfo-2020.owl` into the same world, or add it to `imported_ontologies`). Do not merge-and-flatten; keep it as an import so provenance stays clean.
3. Build a `bfo_catalog` module that reads BFO and exposes, for the UI and the lint:
   - `iri -> rdfs:label` map (so the report shows "quality" not `BFO_0000019`).
   - the full asserted + inferred subclass graph among BFO classes.
   - the full set of `DisjointWith` pairs (not the seven hand-copied ones).

**Acceptance.** The "Ontology Entities" panel renders BFO category labels. A new `/bfo/catalog` debug endpoint (or CLI dump) lists every BFO class with label and parents. The disjointness pair count loaded from BFO is reported and is greater than seven.

---

## 2. Surface incoherence as a first-class result

**Problem.** The current report shows "Consistent" and "No inferred axioms" for an ontology in which `Force`, `Weight`, `Drag`, `Lift`, `Toughness`, `NoiseNuisance`, `InducedDrag`, several `*Load` classes, and the reference-frame classes are unsatisfiable. Consistency (a model exists) is being conflated with coherence (no class equals owl:Nothing).

**Task.**
1. After reasoning, compute the set of **unsatisfiable named classes** (subclasses of `owl:Nothing`). In owlready2 this is `list(default_world.inconsistent_classes())` after `sync_reasoner_pellet()`; via OWLAPI, query each class's satisfiability or read the bottom node of the inferred hierarchy.
2. Add a distinct report section **"Coherence"** separate from **"Consistency"**:
   - Consistency: does a model exist at all (ABox-level).
   - Coherence: list every unsatisfiable class by label.
3. For each unsatisfiable class, attach Pellet's **justification** (the minimal set of axioms entailing the contradiction) and render it in the currently-empty **Derivation Trace** panel. owlready2 exposes explanations via `sync_reasoner_pellet(..., debug=...)`; if the wrapper does not surface justifications, fall back to the lint in Task 3 to produce the explanatory text.
4. The summary banner must not read "Consistent / No contradictions" when unsatisfiable classes exist. Change it to e.g. "Logically consistent, but N classes are unsatisfiable (see Coherence)."

**Acceptance.** Running the existing `aero_base.owl` produces a Coherence section naming at least: `Force`, `Weight`, `DragForce`, `LiftForce`, `FrictionForce`, `Drag`, `Thrust`, `NormalForce`, `Toughness`, `NoiseNuisance`, `InducedDrag`, `AirLoad`, `ShearLoad`, `BendingLoad`, `Lift`, and the reference-frame classes. Each carries at least a one-line justification.

---

## 3. BFO conformance lint (pre-reasoner, fast)

**Problem.** Most real errors here are **partition straddles**: a class transitively under two BFO categories that are disjoint. These are catchable by a graph walk without invoking a DL reasoner, with far better error locality than a raw `owl:Nothing`.

**Task.** Implement `bfo_lint(user_onto, bfo_catalog) -> list[LintFinding]`:
1. For each named user class `C`, compute `bfo_parents(C)` = the set of BFO leaf categories `C` transitively subclasses (walk asserted subclass edges up to BFO nodes).
2. For each unordered pair in `bfo_parents(C)`, test membership in the BFO disjointness closure (two categories clash if they are disjoint **or** sit under disjoint ancestors, e.g. quality under SDC vs disposition under realizable; continuant vs occurrent; material vs immaterial; role vs disposition).
3. Emit a `LintFinding(class, category_a, category_b, message)` with localized, actionable copy. Examples of message style:
   - "`Force` is placed under both Quality and Disposition, which are disjoint. Pick one. If `Force` is a realizable that the bearer is engineered for, model it as a Disposition (or Function) and give the measured magnitude a separate Quality."
   - "`Drag` is both a Quality and a subclass of `AeronauticsActivity` (a Process). Continuant and Occurrent are disjoint. Separate the drag-quality from the drag-generation process."
4. Run the lint **before** the reasoner and render its findings in their own report section. Keep Pellet for entailments the lint cannot see (anything mediated by restrictions rather than raw subclass edges).

**Acceptance.** On `aero_base.owl` the lint independently flags the same families as Task 2's coherence list, with per-class messages, in well under a second, without calling Pellet. Add a unit test fixture (a tiny OWL file with one quality+disposition straddle) asserting exactly one finding.

---

## 4. Inject BFO relation domains and ranges (flagged)

**Problem.** The eleven object properties (`RO_0000052` inheres_in, `RO_0000056` participates_in, `RO_0000087` has_role, `BFO_0000050` part_of, ...) are declared naked: no domain, range, or characteristics. Nothing reasons relationally and nothing prevents pointing `inheres_in` from a quality at a process.

**Task.**
1. Add `bfo/relation-signatures.ttl` encoding BFO's intended domains, ranges, and characteristics for the relations present in the file. At minimum:
   - `inheres_in` (RO_0000052): domain SDC, range independent continuant.
   - `bearer_of` (RO_0000053): inverse of inheres_in.
   - `participates_in` (RO_0000056): domain continuant, range occurrent.
   - `has_participant` (RO_0000057): inverse.
   - `has_role` (RO_0000087): range role.
   - `part_of` (BFO_0000050): transitive; within-category.
2. Provide an **opt-in flag** (`?inject_relation_signatures=true` in the web form, `--inject-relations` on CLI). When set, the signatures are added to the reasoned ontology so misuse clashes instead of passing silently. Default off, so authors see their file's behavior unmodified unless they ask.
3. When the flag is on, any new unsatisfiabilities introduced by the signatures are tagged in the Coherence section as "introduced by BFO relation signatures" so the author can tell told-clashes from signature-clashes.

**Acceptance.** A fixture asserting `q inheres_in p` where `q` is a quality and `p` a process is coherent with the flag off and incoherent (clearly tagged) with it on.

---

## 5. Make the FOL export provable, and fix temporalization

**Problem.** The FOL panel emits only `instance_of(x, Class, t)` membership predicates and bare relation predicates. It emits none of the subsumption conditionals or disjointness negations, so no prover can derive anything. Separately, it temporalizes **every** class uniformly, including occurrents, which mis-models BFO.

**Task.**
1. Extend the FOL generator to emit, in TPTP (preferred, for Vampire/E) or Prover9 syntax:
   - **Subsumptions:** for `Sub ⊑ Super`, `![X,T] : (instance_of(X,sub,T) => instance_of(X,super,T))`.
   - **Disjointness:** for `A ⊥ B`, `![X,T] : ~(instance_of(X,a,T) & instance_of(X,b,T))`.
2. **Fix temporalization per BFO 2020:** continuants take time-indexed instantiation `instance_of(x, C, t)`; occurrents take **atemporal** instantiation `instance_of_at(x, O)` (no `t`), because occurrents carry their temporal parts intrinsically. Decide a class's arity by whether it is under `BFO_0000002` (continuant) or `BFO_0000003` (occurrent) in the catalog. A `Flight` must not instantiate-at-`t` the way a `Wing` does.
3. Add an optional **prover cross-check**: ship the TPTP to a bundled or configured prover (Vampire or E), and report whether the FOL prover's set of unsatisfiable/contradictory classes **agrees** with Pellet's. Disagreement is a tool bug and should be loud. This cross-check is the entire reason a thing named *FOL-BFO-OWL* tester exists.

**Acceptance.** The exported TPTP for `aero_base.owl` is accepted by Vampire and derives the `Force` contradiction. Continuant classes emit ternary `instance_of`, occurrent classes emit binary `instance_of_at`. The report shows "FOL prover and OWL reasoner agree: N unsatisfiable classes" or flags divergence.

---

## 6. Shared asset

Tasks 1, 3, and 4 produce a reusable bundle: vendored BFO 2020, the disjointness-closure structure, and the relation-signature TTL. Factor these into a `bfo/` directory with a stable internal API (`bfo_catalog`, `disjointness_closure()`, `relation_signatures()`). The `bfo-agent` project consumes the **same** bundle so the two tools never disagree about what BFO says. Consider publishing it as a small installable package if both repos can depend on it.

---

## Suggested order

3 → 2 → 1 → 5 → 4. The lint (3) gives the diagnostic surface and needs only the disjointness lattice; wiring it first means every later task has somewhere to report. Pull full BFO (1) once the lint exists to consume it. Relation injection (4) last, since it is opt-in and the highest-friction.
