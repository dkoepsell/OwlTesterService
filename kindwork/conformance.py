"""SHACL conformance over the upload's data (spec section 5, step 5).

Each validation result becomes a `conformance` finding titled with the shape's
sh:message. With no instance data there is nothing to validate and no finding.
"""

from __future__ import annotations

from rdflib import RDF, RDFS, Namespace, URIRef

from kindwork.bundle import local_name
from kindwork.findings import has_notation, make_finding

SH = Namespace("http://www.w3.org/ns/shacl#")


def _message(results, r):
    msgs = list(results.objects(r, SH.resultMessage))
    for m in msgs:
        if getattr(m, "language", None) in (None, "en"):
            return str(m)
    return str(msgs[0]) if msgs else ""


def _target_classes(shapes, data, source, focus):
    node_shapes = set(shapes.subjects(SH.property, source)) | {source}
    targets = {str(c) for ns in node_shapes for c in shapes.objects(ns, SH.targetClass)}
    return sorted(targets) or sorted(str(t) for t in data.objects(focus, RDF.type)
                                     if isinstance(t, URIRef))


def _qname(graph, node):
    try:
        return graph.namespace_manager.normalizeUri(node)
    except Exception:  # noqa: BLE001
        return str(node)


def conformance_findings(bundle):
    if bundle.shapes is None:
        return []
    import pyshacl
    try:
        _, results, _ = pyshacl.validate(bundle.data, shacl_graph=bundle.shapes,
                                         inference="none", allow_warnings=True)
    except Exception as e:  # noqa: BLE001
        return [make_finding(
            "", "conformance", "info", "undetermined", [],
            "The shape rules could not be run",
            "The shapes file was read, but checking the data against it stopped with an "
            "error, so whether the records follow the rules is open.",
            [str(e)])]

    findings, seen = [], set()
    for r in sorted(results.subjects(RDF.type, SH.ValidationResult), key=str):
        focus = results.value(r, SH.focusNode)
        source = results.value(r, SH.sourceShape)
        path = results.value(r, SH.resultPath)
        msg = _message(results, r)
        key = (str(focus), msg, str(path))
        if key in seen:
            continue
        seen.add(key)
        focus_name = (str(bundle.data.value(focus, RDFS.label) or "")
                      or local_name(str(focus)))
        title = msg if msg and not has_notation(msg) else "A record breaks one of the model's rules"
        axioms = [f"focus {_qname(bundle.data, focus)}"]
        if path is not None:
            axioms.append(f"sh:path {_qname(bundle.shapes, path)}")
        if msg and has_notation(msg):
            axioms.append(msg)
        findings.append(make_finding(
            "", "conformance", "info", "fail",
            _target_classes(bundle.shapes, bundle.data, source, focus),
            title, f"The record {focus_name} does not meet this rule.", axioms))
    return findings
