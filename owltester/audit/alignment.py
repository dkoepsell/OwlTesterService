"""R9: BFO alignment, and the gate stages a profile asks for.

In the ``general`` profile alignment is advisory: an artifact that does not use
BFO gets one info finding instead of one failure per class. In ``bfo`` and
``sool`` profiles Stage B keeps its gate severity, and ``sool`` also runs the
whole gate (Stages A to E) with the kernel, as ``owltester check`` does.
"""

import os
import tempfile

from .. import errors
from ..context import GateContext
from ..stages import stage_b
from .schema_checks import qname


def _gate_file(tbox):
    fd, path = tempfile.mkstemp(suffix=".ttl", prefix="audit-gate-")
    os.close(fd)
    tbox.serialize(destination=path, format="turtle")
    return path


def run_r9(ctx):
    art = ctx.artifact
    onto = art.ontology_graph()
    if not len(onto):
        ctx.skip("R9", "BFO alignment", "No ontology file in the artifact.")
        return
    from bfo import load_catalog
    from bfo_lint import bfo_lint
    catalog = load_catalog()
    gate = ctx.profile.get("bfo") == "gate"
    kernel = None
    if "A" in ctx.profile.get("gate", ()):
        from ..kernel import default_kernel_path, load_kernel
        kernel = load_kernel(default_kernel_path())
    path = _gate_file(art.tbox())
    files = [f.path for f in art.by_role("ontology")]
    try:
        gctx = GateContext(path, kernel=kernel, catalog=catalog)
        owned = [c for c in gctx.classes if art.is_owned(c)]
        grounded = [c for c in owned if gctx.bfo_parents(c)]
        notes = {"classes": len(owned), "with_bfo_parent": len(grounded)}
        if not grounded and not gate:
            ctx.add("R9", errors.W_NO_BFO, "info",
                    f"No BFO alignment: {len(owned)} classes have no BFO parent",
                    "Alignment is advisory in the general profile. Use the 'bfo' profile for an "
                    "artifact that claims BFO alignment.", files=files, count=len(owned))
        else:
            result = stage_b.run(gctx)
            by_code = {}
            for f in result.findings:
                if f.iri and not art.is_owned(f.iri):
                    continue
                by_code.setdefault(f.code, []).append(f)
            for code, items in sorted(by_code.items()):
                ctx.add("R9", code, "critical" if gate else "minor",
                        f"{errors.DESCRIPTIONS.get(code, code)}: {len(items)} class(es)",
                        items[0].message + (" (and more)" if len(items) > 1 else ""),
                        files=files, count=len(items),
                        evidence={"classes": [qname(onto, f.iri) if f.iri else f.message
                                              for f in items[:40]]},
                        fix="Place each class under exactly one BFO category, respecting "
                            "BFO's disjointness.")
            straddles = bfo_lint(onto, catalog)
            if straddles and errors.E_DISJOINT not in by_code:
                ctx.add("R9", errors.E_DISJOINT, "critical" if gate else "minor",
                        f"{len(straddles)} classes straddle disjoint BFO categories",
                        straddles[0].message, files=files, count=len(straddles),
                        evidence={"classes": [s.cls for s in straddles[:40]]})
            notes["stage_b"] = result.to_dict()
        if ctx.profile.get("gate") and set(ctx.profile["gate"]) - {"B"}:
            from ..pipeline import check
            from ..kernel import default_kernel_path
            report = check(path, kernel_path=default_kernel_path(), all_stages=True).to_dict()
            notes["gate"] = {"verdict": report["verdict"], "stages": report["stages"]}
            for letter, st in report["stages"].items():
                if letter == "B" or st.get("skipped"):
                    continue
                for d in st.get("details", []):
                    ctx.add("R9", d["code"], "critical", f"Gate stage {letter}: {d['code']}",
                            d["message"], iri=d.get("iri", ""), files=files,
                            suggested_rewrite=d.get("suggested_rewrite", ""))
    finally:
        os.remove(path)
    status = None if ctx.stage_findings("R9") else "pass"
    ctx.finish("R9", "BFO alignment",
               status=status if gate or status else "pass",
               summary=(f"{notes['with_bfo_parent']} of {notes['classes']} classes have a BFO "
                        f"parent; alignment is {'gated' if gate else 'advisory'} in the "
                        f"'{ctx.profile['name']}' profile."),
               notes=notes)
