"""Deterministic JSON-LD (expanded, flattened) for a release graph.

rdflib's JSON-LD serializer follows graph iteration order, which changes with
the hash seed; a release must be byte-identical across builds. Blank nodes are
labelled in a canonical order (rdflib's canonical graph).
"""

import json

from rdflib import BNode, Literal
from rdflib.compare import to_canonical_graph


def _term(t):
    if isinstance(t, BNode):
        return {"@id": f"_:{t}"}
    if isinstance(t, Literal):
        v = {"@value": str(t)}
        if t.language:
            v["@language"] = t.language
        elif t.datatype is not None:
            v["@type"] = str(t.datatype)
        return v
    return {"@id": str(t)}


def _key(v):
    return json.dumps(v, sort_keys=True)


def dumps(graph):
    g = to_canonical_graph(graph)
    nodes = {}
    for s, p, o in g:
        sid = f"_:{s}" if isinstance(s, BNode) else str(s)
        node = nodes.setdefault(sid, {"@id": sid})
        if str(p) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" and not isinstance(o, (Literal, BNode)):
            node.setdefault("@type", []).append(str(o))
        else:
            node.setdefault(str(p), []).append(_term(o))
    out = []
    for sid in sorted(nodes):
        node = nodes[sid]
        clean = {"@id": node["@id"]}
        if "@type" in node:
            clean["@type"] = sorted(set(node["@type"]))
        for k in sorted(k for k in node if not k.startswith("@")):
            clean[k] = sorted({_key(v): v for v in node[k]}.values(), key=_key)
        out.append(clean)
    return json.dumps(out, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
