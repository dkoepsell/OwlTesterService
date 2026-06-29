# owltesterservice — Specification

**Component:** SOoL OWL validation & repair gate (replaces the destructive "autofix")
**Consumes:** any candidate OWL/TTL artifact + `sool-kernel.ttl`
**Produces:** pass/fail verdict, structured report, optional minimally-repaired artifact + quarantine
**Author:** SEAL Lab, Texas A&M · SOoL (Koepsell, Palgrave forthcoming)

---

## 1. Purpose & scope

owltesterservice is the gate every SOoL ontology artifact passes before it is accepted into the corpus, published, or imported by a downstream tool. It validates structure, BFO grounding, logical coherence, and SOoL competency constraints, and — when repair is requested — repairs by **minimal relaxation**, never by bulk deletion.

This spec exists because the prior "autofix" step "fixed" an incoherent ontology by stripping it to 6,881 bare class declarations with 0 axioms — trivially coherent and completely useless. The invariants below make that outcome a guaranteed **build failure**, not a passing result.

**Core rule:** *never silently delete; a coherent-but-empty artifact fails.*

---

## 2. Interfaces

Two entry points over one validation core.

- **CLI / pipeline gate** — `owltester check <artifact> --kernel ...` → exit 0 (pass) / non-zero (fail). For CI and the daily corpus export/FTP pipeline.
- **HTTP service** — `POST /check`, `POST /repair`, `GET /report/{id}`. For interactive use and for bfo-agent's `--gate` hook. JSON in, JSON report out. Suitable for the `seal.tamu.edu` deployment.

Both share identical validation logic; the service is a thin wrapper over the gate library.

---

## 3. Validation pipeline (ordered stages; first hard failure stops the run unless `--all`)

### Stage A — Structural smoke test
Cheap, catches the catastrophic case immediately.

- `A1` axiom count > 0
- `A2` `subClassOf` (logical, non-trivial) count > 0
- `A3` declared `owl:ObjectProperty` count > 0 **and** at least one object-property *assertion/axiom* present (declarations alone do not satisfy A3)
- `A4` BFO anchor classes present **and populated**: `Continuant`, `Occurrent`, `SpecificallyDependentContinuant`, `RealizableEntity`, `Role`, `MaterialEntity`, `GenericallyDependentContinuant` each exist and have ≥1 subclass or instance. Bare `BFO_xxxxxxx` fragment stubs with nothing under them fail A4.
- `A5` class count within `[kernel_size, kernel_size × max_factor]` (default `max_factor = 4`). A 6,881-class artifact against a ~150-class kernel fails A5.
- `A6` no class matches the privation/compound anti-pattern regex (mirror of bfo-agent PC-1/PC-2), so a degenerate artifact can't slip in from another producer.

### Stage B — BFO grounding
- `B1` every domain class reaches a BFO upper category via `subClassOf*` (no orphans).
- `B2` no class is both `Continuant` and `Occurrent` (disjointness honored).
- `B3` node-type typing matches the kernel: norms/roles/obligations/effects ⊑ specifically dependent continuant; agents ⊑ material entity; legal events ⊑ occurrent. Mismatches are errors, listed per class.

### Stage C — Reasoner coherence **and** non-triviality
- `C1` runs HermiT (or ELK for the EL profile) to confirm logical consistency and class satisfiability.
- `C2` **non-triviality:** an artifact that is consistent *only because it asserts nothing* fails. Require that consistency is non-vacuous — i.e., the artifact still satisfies Stage A/B after reasoning, and the reasoner actually entailed ≥1 non-asserted subsumption over kernel terms. Trivial coherence is a failure mode, not a pass.
- `C3` on inconsistency, compute and report the **minimal unsatisfiable cores** (justifications / MUPS), not just a boolean.

### Stage D — SOoL competency constraints (SHACL + competency questions)
Encoded as SHACL shapes and/or SPARQL ASKs, versioned alongside the kernel:
- `D1` every `Norm` instance is a specifically dependent continuant.
- `D2` every asserted Legal Effect traces a closeable MLC path, or carries an explicit contradiction-type individual explaining the break.
- `D3` every contradiction instance is indexed to an MLC link and typed to one of the 13 kernel types.
- `D4` no `AbsenceOf*`/`Lack*`/`Failure*` named class exists (failure must be a typology instance).
- `D5` every Actor-in-Role role inheres in a material-entity bearer.
Competency questions are stored as fixtures so new ones accrete over time (supports populating the SEAL case library).

### Stage E — Delta invariant (only for `repair`, or when an input baseline is supplied)
- `E1` `out.axioms ≥ in.axioms − |logged_removals|`. Any reduction not itemized in the removal log fails the build.
- `E2` `out.objectProperties ≥ in.objectProperties` unless each drop is logged with justification.
- `E3` hard tripwire: if `in.axioms > 0` and `out.axioms == 0`, **fail immediately** with `E_TRIVIALIZED`. (This is the exact failure that produced `SOOL_autofixed.owl`.)

---

## 4. Repair behavior (`POST /repair` / `owltester repair`)

Repair is opt-in and conservative. It replaces "autofix."

1. Run Stage C; if consistent, no repair — return input unchanged.
2. If inconsistent, compute justifications / MUPS for each unsatisfiable class.
3. Relax **only** axioms inside the minimal cores, choosing the smallest hitting set that restores satisfiability. This is the same relaxation philosophy already in `patch_reasoner.py` (the 9 residual structural impossibilities, ~0.16% of cases) — point repair at that mechanism rather than re-implementing deletion.
4. Every relaxed/removed axiom is written to `quarantine.ttl` with its justification and the core it belonged to. Nothing is dropped silently.
5. Axioms the FOL translator cannot process are **quarantined for review, never deleted** — quarantine is the default disposition for anything untranslatable.
6. Re-run the full pipeline on the repaired artifact; repair "succeeds" only if the result passes A–E **and** the removal log fully accounts for every delta.

`max_removed_axioms` is bounded (default: 2% of input, configurable). Exceeding it fails with `E_OVER_RELAXED` rather than producing a hollowed-out ontology.

---

## 5. Failure taxonomy & exit codes

| Code | Meaning | Stage |
|---|---|---|
| `E_NO_AXIOMS` | artifact has no logical axioms | A1 |
| `E_FLAT` | no subClassOf / no object-property axioms | A2/A3 |
| `E_NO_BFO` | BFO anchors absent or unpopulated | A4 |
| `E_BLOATED` | class count exceeds kernel × max_factor | A5 |
| `E_ANTIPATTERN` | privation/compound class present | A6/D4 |
| `E_ORPHAN` | class not grounded to BFO | B1 |
| `E_DISJOINT` | Continuant/Occurrent conflation | B2 |
| `E_MISTYPED` | node BFO type ≠ kernel | B3 |
| `E_INCONSISTENT` | reasoner inconsistency (+ MUPS) | C1 |
| `E_TRIVIAL` | coherent only because vacuous | C2 |
| `E_COMPETENCY` | SHACL/competency-question violation | D |
| `E_TRIVIALIZED` | input had axioms, output has none | E3 |
| `E_OVER_RELAXED` | repair removed more than the bound | repair |
| `0` | pass | — |

Reports list every failure with offending IRIs and, where relevant, a suggested rewrite, so failures are actionable rather than just blocking.

---

## 6. Report format (`GET /report/{id}`)

```json
{
  "artifact": "case-0001.ttl",
  "kernel_version": "sool-kernel/1.x",
  "verdict": "fail",
  "counts": { "classes": 6881, "subClassOf": 0, "objectProperties": 0,
              "individuals": 0, "axioms": 0 },
  "stages": {
    "A": { "pass": false, "failures": ["E_NO_AXIOMS","E_FLAT","E_NO_BFO","E_BLOATED"] },
    "B": { "skipped": "halted at A" }
  },
  "antipattern_hits": ["AbsenceOfRecognition","NormAlignmentWithRuleOfRecognition", "..."],
  "removals": [],
  "suggested_rewrites": { "AbsenceOfRecognition": "instance of RecognitionFailure @ MLC 6/7" }
}
```

---

## 7. Acceptance criteria & regression suite

1. **Golden-bad fixture.** `SOOL_autofixed.owl` is committed as a regression fixture. `owltester check` on it MUST return non-zero with `E_NO_AXIOMS, E_FLAT, E_NO_BFO, E_BLOATED, E_ANTIPATTERN`. If this file ever passes, the gate is broken.
2. **Golden-good fixture.** A small hand-built kernel-conformant case fragment MUST pass all stages.
3. **Trivialization guard.** A test that feeds a valid artifact and a deletion-style "repair" must trip `E_TRIVIALIZED`.
4. **Non-vacuity guard.** An artifact stripped to consistent-but-empty must trip `E_TRIVIAL` at C2.
5. **Delta accounting.** A repair that removes an axiom without logging it must fail E1.
6. **Pipeline wiring.** The daily corpus export and the bfo-agent `--gate` hook both call the gate and abort on non-zero before any FTP upload or durable write.

---

## 8. CLI contract

```
# Gate (CI / pipeline)
owltester check <artifact.ttl> --kernel sool-kernel.ttl [--all] [--json report.json]
#   exit 0 pass, non-zero fail.

# Repair (conservative, logged)
owltester repair <artifact.ttl> --kernel sool-kernel.ttl \
  --out repaired.ttl --quarantine quarantine.ttl \
  --max-removed 0.02
#   exit 0 only if repaired artifact passes the full pipeline AND every delta is logged.

# Service
owltester serve --port 8080 --kernel sool-kernel.ttl
#   POST /check  POST /repair  GET /report/{id}
```

---

## 9. Dependencies & notes

- Reasoners: HermiT (DL) and ELK (EL profile) — pick by ontology profile; both already in the SEAL stack.
- SHACL engine for Stage D (pySHACL or equivalent); shapes versioned with the kernel.
- Repair reuses the `patch_reasoner.py` relaxation path rather than re-implementing axiom removal.
- The gate is intentionally stricter than OWL validity: an artifact can be valid OWL and still fail (e.g., flat, trivial, or off-vocabulary). SOoL conformance ⊃ OWL validity.
