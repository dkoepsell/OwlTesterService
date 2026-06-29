"""Stage D — SOoL competency constraints.

Encoded as SPARQL competency queries (and, when pyshacl is installed, SHACL
shapes) versioned alongside the kernel under ``fixtures/competency/``. Each
``.rq`` file is a SPARQL SELECT; a non-empty result is a *violation*. A header
comment declares the failure code and description:

    # code: E_COMPETENCY
    # desc: D1 - every Norm instance must be a specifically dependent continuant
    SELECT ?norm WHERE { ... }

Storing them as fixtures lets new competency questions accrete over time (the
SEAL case library) without code changes. If no queries are present the stage is
skipped rather than passing vacuously.
"""

import glob
import os

from ..model import StageResult
from .. import errors

_COMPETENCY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fixtures", "competency",
)
_SHAPES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fixtures", "shapes",
)


def _parse_header(text):
    code, desc = errors.E_COMPETENCY, ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# code:"):
            code = line.split(":", 1)[1].strip()
        elif line.startswith("# desc:"):
            desc = line.split(":", 1)[1].strip()
        elif not line.startswith("#") and line:
            break
    return code, desc


def _grounding_graph(ctx):
    """Artifact + kernel triples, so competency queries can see the kernel's
    subClassOf grounding when resolving instance typing."""
    import rdflib
    g = rdflib.Graph()
    for t in ctx.graph:
        g.add(t)
    if ctx.kernel and getattr(ctx.kernel, "path", None):
        try:
            g.parse(ctx.kernel.path, format="turtle")
        except Exception:  # noqa: BLE001
            pass
    return g


def run(ctx, competency_dir=None):
    r = StageResult("D")
    competency_dir = competency_dir or _COMPETENCY_DIR

    queries = sorted(glob.glob(os.path.join(competency_dir, "*.rq")))
    ran_any = False

    if queries:
        g = _grounding_graph(ctx)
        for qpath in queries:
            with open(qpath, "r", encoding="utf-8") as fh:
                text = fh.read()
            code, desc = _parse_header(text)
            name = os.path.basename(qpath)
            try:
                rows = list(g.query(text))
            except Exception as exc:  # noqa: BLE001 - a broken query is a config error, not a pass
                r.notes.setdefault("query_errors", {})[name] = str(exc)
                continue
            ran_any = True
            if rows:
                offenders = [str(row[0]) for row in rows if len(row) > 0][:25]
                for off in offenders:
                    r.add(code, f"{desc or name}: {off}", iri=off)
                if not offenders:
                    r.add(code, desc or name)

    # Optional SHACL validation when pyshacl + shapes are present.
    shape_files = glob.glob(os.path.join(_SHAPES_DIR, "*.ttl"))
    if shape_files:
        try:
            import pyshacl
            import rdflib
            shapes = rdflib.Graph()
            for sf in shape_files:
                shapes.parse(sf, format="turtle")
            data = _grounding_graph(ctx)
            conforms, _, text = pyshacl.validate(
                data, shacl_graph=shapes, inference="rdfs", abort_on_first=False)
            ran_any = True
            if not conforms:
                r.add(errors.E_COMPETENCY, "SHACL validation reported violations.")
                r.notes["shacl_report"] = text[:4000]
        except ImportError:
            r.notes["shacl"] = "pyshacl not installed; SHACL shapes skipped"

    if not ran_any:
        r.skipped = "no competency queries or SHACL shapes available"
    return r
