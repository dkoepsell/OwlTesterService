"""The validation core shared by the CLI gate and the HTTP service.

Stages run in order A -> B -> C -> D -> E. The first hard failure stops the run
unless ``all_stages=True`` (the ``--all`` flag), in which case every stage runs
and the report lists all failures. Stages downstream of a stop are marked
``skipped`` with the halt reason.
"""

from .context import GateContext
from .counts import count, load_graph
from .kernel import load_kernel
from .model import Report
from .stages import stage_a, stage_b, stage_c, stage_d, stage_e

_STAGES = [("A", stage_a), ("B", stage_b), ("C", stage_c), ("D", stage_d), ("E", stage_e)]


def _load_catalog():
    try:
        from bfo.catalog import load_catalog
        return load_catalog()
    except Exception:  # noqa: BLE001 - catalog is optional; B2/B3 degrade without it
        return None


def check(path, kernel_path=None, all_stages=False, baseline_counts=None,
          removals=None, catalog=None):
    """Run the gate over ``path``. Returns a Report.

    ``baseline_counts`` (a Counts) activates Stage E; pass it when validating a
    repair output or any time an input baseline is known.
    """
    kernel = load_kernel(kernel_path)
    if catalog is None:
        catalog = _load_catalog()

    ctx = GateContext(path, kernel=kernel, catalog=catalog,
                      baseline=baseline_counts, removals=removals)

    report = Report(artifact=str(path), kernel_version=kernel.version)
    report.counts = ctx.counts.to_dict()

    halted = None
    for letter, mod in _STAGES:
        # E only runs when a baseline is present.
        if letter == "E" and baseline_counts is None:
            res = mod.run(ctx)  # records its own "skipped" reason
            report.stages[letter] = res.to_dict()
            continue
        if halted and not all_stages:
            report.stages[letter] = {"skipped": f"halted at {halted}"}
            continue
        res = mod.run(ctx)
        report.stages[letter] = res.to_dict()
        # collect antipattern hits + suggested rewrites for the top-level report
        if letter == "A":
            report.antipattern_hits = res.notes.get("antipattern_hits", [])
        for f in res.findings:
            if f.suggested_rewrite:
                report.suggested_rewrites[f.iri or f.code] = f.suggested_rewrite
        if not res.passed and halted is None:
            halted = letter

    return report


def baseline_for(path):
    """Counts for an input artifact, to feed Stage E of a later check."""
    return count(load_graph(path))
