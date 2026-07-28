"""Contradiction debt (paper §7).

For a recognition-constituted ontology O, the contradiction debt of a category
x is the weighted sum of the typed defects sitting at x, and CD(O) aggregates
that over the artifact's categories, normalized so artifacts of different sizes
can be compared.

**This is not an inconsistency measure.** §7.4 is explicit and it matters here
because the name invites the confusion. K-B3 and K-C2 fire on artifacts that
are entirely consistent -- a residual definition and a punned term are defects
of a perfectly satisfiable theory -- so CD is not a measure of inconsistency in
the Hunter-Konieczny sense, and Monotony fails for it. Nothing in this module
should be reported as an inconsistency score.

Two corrections are applied, both of which the paper had to make to its own
headline numbers:

*Blanket flags* (§9.3). A flag applied to every member of a branch because
their shared parent carries a contestable typing decision is one modelling
decision, not N discoveries. Separating it out is what collapsed the paper's
own flagship density figure from 1.123 to 0.129 -- an order of magnitude, and
the corrected reading is the one it defends.

*Artifactual defects* (§10.1). A defect our extraction introduced is not a
defect of the classification. Counting it inflates the debt of whatever source
we happened to translate badly.

Both readings are reported. The raw figure is kept because hiding it would make
the correction unauditable.
"""

from .kernel import CHAIN_LOCI, KERNEL, LOCUS_KEYS

# Type-fixed weights. Deliberately uniform: a weighted count needs a defended
# weighting, and the paper does not supply one. An honest typed count is a
# better default than an invented severity ranking, and callers who have a
# domain-specific weighting can pass their own.
DEFAULT_WEIGHTS = {k["id"]: 1.0 for k in KERNEL}


def weight_for(kernel_id, weights=None):
    return (weights or DEFAULT_WEIGHTS).get(kernel_id, 1.0)


def debt_by_locus(findings, weights=None, corrected=True):
    """CD(x) for each chain locus, plus an ``unbound`` bucket.

    ``corrected=True`` drops blanket flags and artifact-attributed defects.
    """
    buckets = {k: 0.0 for k in LOCUS_KEYS}
    buckets["unbound"] = 0.0
    for f in findings:
        if corrected and not f.counts_toward_debt:
            continue
        key = f.locus if f.locus in buckets else "unbound"
        buckets[key] += weight_for(f.kernel, weights)
    return buckets


def debt_by_stratum(findings, weights=None, corrected=True):
    buckets = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
    for f in findings:
        if corrected and not f.counts_toward_debt:
            continue
        if f.stratum in buckets:
            buckets[f.stratum] += weight_for(f.kernel, weights)
    return buckets


def _total(findings, weights, corrected):
    return sum(weight_for(f.kernel, weights) for f in findings
               if not corrected or f.counts_toward_debt)


def compute(findings, category_count, weights=None):
    """The full measure: raw, corrected, and the breakdown behind each.

    ``category_count`` is the number of categories the debt is spread over --
    the artifact's named classes. Normalizing by it is what makes the figure
    comparable across artifacts of different sizes, and it is why the paper can
    put a 3,498-class disease branch beside a 26-class genetic one.
    """
    total_raw = _total(findings, weights, corrected=False)
    total_corrected = _total(findings, weights, corrected=True)
    n = max(1, int(category_count or 0))

    excluded_blanket = [f for f in findings if f.flag_scope == "blanket"]
    excluded_artifact = [f for f in findings if f.attribution == "artifact"]

    return {
        "category_count": int(category_count or 0),
        "cd_raw": round(total_raw / n, 4),
        "cd_corrected": round(total_corrected / n, 4),
        "total_raw": total_raw,
        "total_corrected": total_corrected,
        "by_locus": {k: round(v, 4) for k, v in
                     debt_by_locus(findings, weights).items()},
        "by_locus_raw": {k: round(v, 4) for k, v in
                         debt_by_locus(findings, weights,
                                       corrected=False).items()},
        "by_stratum": {k: round(v, 4) for k, v in
                       debt_by_stratum(findings, weights).items()},
        "excluded": {
            "blanket": len(excluded_blanket),
            "artifact_attributed": len(excluded_artifact),
        },
        "weighting": "uniform" if weights is None else "custom",
        "not_an_inconsistency_measure": (
            "CD counts typed defects, several of which occur in perfectly "
            "consistent artifacts. It is not an inconsistency measure in the "
            "Hunter-Konieczny sense and Monotony fails for it."),
    }


def locus_table(findings, weights=None):
    """Per-locus rows for the report page, in chain order."""
    corrected = debt_by_locus(findings, weights)
    raw = debt_by_locus(findings, weights, corrected=False)
    counts = {k: 0 for k in list(corrected)}
    for f in findings:
        key = f.locus if f.locus in counts else "unbound"
        counts[key] += 1

    rows = []
    for locus in CHAIN_LOCI:
        key = locus["key"]
        rows.append({
            "key": key,
            "name": locus["name"],
            "gloss": locus["gloss"],
            "findings": counts[key],
            "debt": round(corrected[key], 4),
            "debt_raw": round(raw[key], 4),
        })
    rows.append({
        "key": "unbound",
        "name": "Not bound to a locus",
        "gloss": "Defects on entities the chain binding could not place.",
        "findings": counts["unbound"],
        "debt": round(corrected["unbound"], 4),
        "debt_raw": round(raw["unbound"], 4),
    })
    return rows
