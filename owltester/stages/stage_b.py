"""Stage B — BFO grounding.

B1 every domain class reaches a BFO upper category (no orphans).
B2 no class straddles a BFO disjoint partition (e.g. Continuant & Occurrent).
B3 node typing matches the kernel: a class under a SOoL category must ground to
   that category's required BFO anchor, not a disjoint one.
"""

from ..model import StageResult
from .. import errors
from ..kernel import ANCHOR_IRIS


def _local(iri):
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def run(ctx):
    r = StageResult("B")
    catalog = ctx.catalog

    domain_classes = [c for c in ctx.classes if not ctx.is_bfo(c)]

    # B1 — orphans. Cap the per-class detail so a wholesale-ungrounded artifact
    # does not produce a multi-thousand-line report; the count is still exact.
    orphans = [c for c in sorted(domain_classes)
               if c not in ANCHOR_IRIS and not ctx.bfo_parents(c)]
    for cls in orphans[:50]:
        r.add(errors.E_ORPHAN,
              f"'{_local(cls)}' does not reach any BFO upper category via "
              f"subClassOf*.", iri=cls,
              suggested_rewrite=f"add subClassOf to the BFO category that fits {_local(cls)}")
    if orphans:
        r.notes["orphan_count"] = len(orphans)
        if len(orphans) > 50:
            r.notes["orphans_truncated"] = len(orphans) - 50

    # B2 — disjoint straddles. Needs the catalog's disjointness closure.
    if catalog is None:
        r.notes["B2"] = "skipped: BFO catalog unavailable"
    else:
        for cls in sorted(domain_classes):
            parents = sorted(ctx.bfo_parents(cls))
            for i in range(len(parents)):
                for j in range(i + 1, len(parents)):
                    a, b = parents[i], parents[j]
                    if catalog.clash(a, b):
                        r.add(errors.E_DISJOINT,
                              f"'{_local(cls)}' is under both {catalog.label_for(a)} "
                              f"and {catalog.label_for(b)}, which are disjoint in "
                              f"BFO 2020.", iri=cls)

    # B3 — kernel node typing.
    if not ctx.kernel.categories:
        r.notes["B3"] = "skipped: kernel declares no SOoL typing"
    elif catalog is None:
        r.notes["B3"] = "skipped: BFO catalog unavailable"
    else:
        for cat in ctx.kernel.categories:
            required = cat.required_anchor
            for cls in sorted(domain_classes):
                if cls == cat.iri:
                    continue
                if not ctx.reaches(cls, cat.iri):
                    continue
                # the class is a kind of this SOoL category; it must not reach a
                # BFO anchor disjoint from the category's required anchor.
                for anchor in ctx.bfo_parents(cls):
                    if anchor in ANCHOR_IRIS and catalog.clash(required, anchor):
                        r.add(errors.E_MISTYPED,
                              f"'{_local(cls)}' is a {cat.label} so must ground to "
                              f"{catalog.label_for(required)}, but it also reaches "
                              f"the disjoint {catalog.label_for(anchor)}.", iri=cls)

    return r
