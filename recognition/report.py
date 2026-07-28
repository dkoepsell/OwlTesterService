"""Assembling a recognition-layer report for one artifact.

The order matters and is not arbitrary:

  1. bind the artifact's entities to recognition-chain loci
  2. run whichever detectors are available, recording *which* ran
  3. attribute what our own translation is responsible for
  4. build the fingerprint, told honestly what was and was not assessed

Step 2's bookkeeping is the part that is easy to skip and expensive to skip.
A report that lists findings without recording which instruments produced them
cannot distinguish an empty stratum from an unexamined one, and an empty
stratum reads as a clean bill of health.
"""

from dataclasses import dataclass, field

from . import (attribution, binding as binding_mod, measure as measure_mod,
               profile as profile_mod)
from .kernel import KERNEL, STRATA, VOCABULARY_VERSION
from .detectors import dl as dl_detector
from .detectors import prover as prover_detector
from .detectors import stratum_d as stratum_d_detector
from .detectors import structural as structural_detector


@dataclass
class RecognitionReport:
    artifact: str
    vocabulary_version: str = VOCABULARY_VERSION
    fingerprint: dict = field(default_factory=dict)
    chain: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)      # RecognitionFinding
    primitives_attempted: set = field(default_factory=set)
    instrument_notes: dict = field(default_factory=dict)
    measure: dict = field(default_factory=dict)
    locus_table: list = field(default_factory=list)

    def by_stratum(self):
        counts = {s["key"]: 0 for s in STRATA}
        for f in self.findings:
            if f.stratum in counts:
                counts[f.stratum] += 1
        return counts

    def to_dict(self):
        return {
            "artifact": self.artifact,
            "vocabulary_version": self.vocabulary_version,
            "fingerprint": self.fingerprint,
            "chain": self.chain,
            "findings": [f.to_dict() for f in self.findings],
            "counts_by_stratum": self.by_stratum(),
            "primitives_attempted": sorted(self.primitives_attempted),
            "primitives_not_attempted": sorted(
                k["id"] for k in KERNEL
                if k["id"] not in self.primitives_attempted),
            "instrument_notes": self.instrument_notes,
            "measure": self.measure,
            "locus_table": self.locus_table,
        }


def _run_stage_c(ctx):
    """Stage C's reasoner result, or None with a reason if it could not run."""
    try:
        from owltester.stages import stage_c
        result = stage_c.run(ctx)
    except Exception as exc:  # noqa: BLE001 - reasoner is optional here
        return None, f"reasoner unavailable: {exc}"
    if result.skipped:
        return None, result.skipped
    return result, ""


def _run_bfo_lint(ctx):
    try:
        from bfo_lint import bfo_lint
        return bfo_lint(ctx.graph, ctx.catalog), ""
    except Exception as exc:  # noqa: BLE001
        return [], f"bfo lint unavailable: {exc}"


def _dedupe_cycles(findings):
    """Collapse K-B1 findings that report the same cycle twice.

    The DL detector walks subClassOf and the structural detector walks
    definitions, so a term that is both subsumed by and defined through its own
    descendant surfaces in both. It is one circularity at one locus, and
    counting it twice would inflate the debt measure. The surviving finding
    keeps both routes in its evidence.
    """
    kept = []
    by_cycle = {}
    for f in findings:
        if f.kernel != "K-B1" or "cycle" not in f.evidence:
            kept.append(f)
            continue
        key = frozenset(f.evidence["cycle"])
        first = by_cycle.get(key)
        if first is None:
            by_cycle[key] = f
            f.evidence["kinds"] = [f.evidence.get("kind", "")]
            kept.append(f)
        else:
            first.evidence["kinds"].append(f.evidence.get("kind", ""))
    return kept


def build(ctx, overrides=None, declared_object_class="", use_reasoner=True,
          record=None, weights=None, use_prover=True):
    """The recognition-layer report for an already-built GateContext.

    ``use_reasoner=False`` suppresses the HermiT pass only. The rest of the DL
    instrument -- category clashes from upper-level disjointness, subsumption
    cycles, unborne dependents -- is graph walking over asserted axioms and
    still runs, because switching it off would silently widen the unassessed
    region without saying so.

    ``record`` is the declared institutional record that Stratum D needs; see
    ``detectors.stratum_d``. Without one, K-D1 through K-D3 go unattempted.
    """
    chain = binding_mod.propose(ctx, overrides=overrides)
    notes = {}

    stage_c_result = None
    if use_reasoner:
        stage_c_result, reason = _run_stage_c(ctx)
        if reason:
            notes["reasoner"] = reason
    else:
        notes["reasoner"] = "not run (use_reasoner=False)"

    lint_findings, lint_reason = _run_bfo_lint(ctx)
    if lint_reason:
        notes["bfo_lint"] = lint_reason

    result = dl_detector.run(ctx, chain, stage_c_result, lint_findings,
                             lint_ran=not lint_reason)
    result.extend(structural_detector.run(ctx, chain))
    result.extend(stratum_d_detector.run(record, chain))
    notes.update(result.notes)

    result.findings = _dedupe_cycles(result.findings)

    # Promote structural suspicions to demonstrated unintended models where a
    # model finder can witness one. Adds evidence, never a primitive.
    if use_prover:
        prover_detector.run(result.findings)

    attribution.apply(result.findings, ctx)

    counts = {s["key"]: 0 for s in STRATA}
    for f in result.findings:
        if f.stratum in counts:
            counts[f.stratum] += 1

    fingerprint = profile_mod.build(
        chain,
        primitives_attempted=result.attempted,
        declared_object_class=declared_object_class,
        observed_counts=counts)

    return RecognitionReport(
        artifact=ctx.path,
        fingerprint=fingerprint.to_dict(),
        chain=chain.to_dict(),
        findings=result.findings,
        primitives_attempted=result.attempted,
        instrument_notes=notes,
        measure=measure_mod.compute(result.findings, len(ctx.classes), weights),
        locus_table=measure_mod.locus_table(result.findings, weights))


def build_for_path(path, kernel_path=None, catalog=None, **kwargs):
    """Convenience wrapper that builds the GateContext itself."""
    from owltester.context import GateContext
    from owltester.kernel import load_kernel

    if catalog is None:
        try:
            from bfo.catalog import load_catalog
            catalog = load_catalog()
        except Exception:  # noqa: BLE001 - corroboration degrades without it
            catalog = None
    ctx = GateContext(path, kernel=load_kernel(kernel_path), catalog=catalog)
    return build(ctx, **kwargs)
