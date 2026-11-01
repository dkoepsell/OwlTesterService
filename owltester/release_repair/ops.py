"""The closed set of change operations (spec section 3.3) and their guards.

Repair may do only these things. Every op works on a copy of the release (a
``Tree``), checks its guard before it writes, and returns a record of what it
changed. A failed guard raises ``OpError`` and the caller abandons the apply.

Terms inside ops are N3 strings: ``<iri>``, ``"text"@en``, ``"1"^^<xsd:int IRI>``
and, for blank nodes, the canonical labels of ``rdflib.compare`` (``_:cb...``),
which are stable for a file whose content around the node has not changed.
"""

import difflib
import re

import rdflib
from rdflib import RDF, BNode, Literal, URIRef
from rdflib.util import from_n3

from .tree import (WRITE_FORMATS, OpError, Tree, _ext, _same, canonical_graph, n3,  # noqa: F401
                   read_format, save_graph, serialize)

OP_NAMES = ("rewrite_iri", "set_literal", "add_triples", "remove_triples", "retype",
            "merge_nodes", "write_text", "exclude_file")

def term(n3):
    """Parse an N3 term string from an op."""
    if isinstance(n3, (URIRef, Literal, BNode)):
        return n3
    text = str(n3).strip()
    if text.startswith("_:"):
        return BNode(text[2:])
    try:
        t = from_n3(text)
    except Exception as e:  # noqa: BLE001
        raise OpError(f"not an RDF term: {text[:80]!r} ({e})")
    if t is None:
        raise OpError(f"not an RDF term: {text[:80]!r}")
    return t


def triple(row):
    if not isinstance(row, (list, tuple)) or len(row) != 3:
        raise OpError(f"a triple needs three terms: {row!r}")
    return tuple(term(x) for x in row)


def _has_bnode(rows):
    return any(str(x).startswith("_:") for r in rows for x in r)


# -- each op -----------------------------------------------------------------------------

def count_refs(g, old, mode):
    """How many term positions in ``g`` the rewrite would change."""
    n = 0
    for t in g:
        for x in t:
            if isinstance(x, URIRef) and (str(x) == old if mode == "iri" else str(x).startswith(old)):
                n += 1
            elif isinstance(x, Literal) and x.datatype is not None and \
                    (str(x.datatype) == old if mode == "iri" else str(x.datatype).startswith(old)):
                n += 1
    return n


def _map_iri(x, old, new, mode):
    if isinstance(x, URIRef):
        s = str(x)
        if mode == "iri" and s == old:
            return URIRef(new)
        if mode == "namespace" and s.startswith(old):
            return URIRef(new + s[len(old):])
    if isinstance(x, Literal) and x.datatype is not None:
        d = _map_iri(URIRef(x.datatype), old, new, mode)
        if d != x.datatype:
            return Literal(str(x), datatype=d)
    return x


def op_rewrite_iri(tree, args):
    old, new, mode = str(args["from"]), str(args["to"]), args.get("mode", "namespace")
    if mode not in ("namespace", "iri") or not old or not new or old == new:
        raise OpError("rewrite_iri needs distinct 'from' and 'to' and a mode")
    expect = args.get("expect") or {}
    changed = {}
    for rel in args.get("files") or []:
        g = tree.graph(rel)
        n = count_refs(g, old, mode)
        if rel in expect and n != expect[rel]:
            raise OpError(f"{rel}: {n} references to {old}, but the preview counted {expect[rel]}; "
                          "the release changed since the plan was made")
        if not n:
            continue
        target = rdflib.Graph()
        for prefix, ns in g.namespaces():
            if mode == "namespace" and str(ns).startswith(old):
                ns = new + str(ns)[len(old):]
            target.bind(prefix, ns, override=True, replace=True)
        for t in g:
            target.add(tuple(_map_iri(x, old, new, mode) for x in t))
        after = count_refs(target, old, mode)
        if after:
            raise OpError(f"{rel}: the rewrite left {after} references to {old}")
        text = tree.read(rel)
        candidate = _text_rewrite(text, old, new, mode)
        written = False
        if candidate != text:
            tree.write(rel, candidate)
            try:
                written = _same(tree.graph(rel), target)
            except OpError:
                written = False
            if not written:
                tree.write(rel, text)
        if not written:
            save_graph(tree, rel, target)
        tree.forget(rel)
        changed[rel] = n
    return {"references_rewritten": changed, "triples_added": 0, "triples_removed": 0}


def _text_rewrite(text, old, new, mode):
    """Replace the IRI or namespace where it is written out in full (between angle
    brackets or quotes). Prefixed names follow their @prefix line. The result is
    accepted only if it parses to exactly the rewritten graph."""
    if mode == "iri":
        pattern = re.compile(r"(?<=[<\"'])" + re.escape(old) + r"(?=[>\"'])")
        return pattern.sub(new.replace("\\", "\\\\"), text)
    pattern = re.compile(r"(?<=[<\"'])" + re.escape(old))
    return pattern.sub(new.replace("\\", "\\\\"), text)


def op_set_literal(tree, args):
    rel = args["file"]
    rows = args.get("changes") or []
    g = tree.graph(rel)
    done = 0
    for row in rows:
        if len(row) != 4:
            raise OpError("set_literal rows are [subject, predicate, old literal, new literal]")
        s, p, old, new = (term(x) for x in row)
        if not isinstance(old, Literal) or not isinstance(new, Literal):
            raise OpError("set_literal changes literals only")
        if str(old) != str(new):
            raise OpError("set_literal may change a language tag or datatype, not the text")
        if (s, p, old) not in g:
            raise OpError(f"{rel}: the literal {old.n3()[:80]} is no longer there")
        g.remove((s, p, old))
        g.add((s, p, new))
        done += 1
    save_graph(tree, rel, g)
    return {"literals_changed": done, "triples_added": 0, "triples_removed": 0}


def _check_new_terms(g, guard):
    """New subjects in owned namespaces or already declared (spec 3.3)."""
    if not guard:
        return
    owned, declared = guard.get("owned", []), set(guard.get("declared", []))
    for s in set(g.subjects()):
        if isinstance(s, URIRef) and str(s) not in declared and \
                not any(str(s).startswith(o) for o in owned):
            raise OpError(f"{s} is neither declared nor in one of the release's own namespaces")


def _add_rows(tree, rel, rows, guard):
    """Add explicit triples; blank nodes must already exist in the file."""
    g = tree.graph(rel)
    rows = [triple(r) for r in rows]
    known = {x for t in g for x in t if isinstance(x, BNode)}
    new = rdflib.Graph()
    for t in rows:
        if any(isinstance(x, BNode) and x not in known for x in t):
            raise OpError(f"{rel}: a blank node to extend is no longer there")
        if t not in g:
            new.add(t)
    _check_new_terms(new, guard)
    for t in new:
        g.add(t)
    if len(new):
        save_graph(tree, rel, g)
    return {"triples_added": len(new), "triples_removed": 0}


def op_add_triples(tree, args, guard=None):
    rel = args["file"]
    if args.get("triples"):
        return _add_rows(tree, rel, args["triples"], guard)
    text = str(args.get("turtle") or "")
    snippet = rdflib.Graph()
    try:
        snippet.parse(data=text, format="turtle")
    except Exception as e:  # noqa: BLE001
        raise OpError(f"the Turtle to add does not parse: {str(e)[:200]}")
    if not len(snippet):
        raise OpError("nothing to add")
    _check_new_terms(snippet, guard)
    exists = tree.exists(rel)
    if exists and read_format(tree.path(rel)) == "turtle":
        # Append the snippet as written, so the diff shows exactly what was added;
        # fall back to rewriting the file if the result is not the expected union.
        g = tree.graph(rel)
        new = [t for t in snippet if t not in g]
        if not new:
            return {"triples_added": 0, "triples_removed": 0}
        current = tree.read(rel)
        tree.write(rel, current.rstrip("\n") + "\n\n# Added by guided release repair\n"
                   + text.strip() + "\n")
        try:
            merged = tree.graph(rel)
            ok = len(merged) == len(g) + len(new) and \
                all(t in merged for t in g if not any(isinstance(x, BNode) for x in t))
        except OpError:
            ok = False
        if not ok:
            union = rdflib.Graph()
            for prefix, ns in list(g.namespaces()) + list(snippet.namespaces()):
                union.bind(prefix, ns, override=False)
            for t in list(g) + new:
                union.add(t)
            tree.write(rel, current)
            save_graph(tree, rel, union)
        tree.forget(rel)
        return {"triples_added": len(new), "triples_removed": 0}
    g = tree.graph(rel) if exists else rdflib.Graph()
    before = len(g)
    for prefix, ns in snippet.namespaces():
        g.bind(prefix, ns, override=False)
    for t in snippet:
        g.add(t)
    if exists:
        save_graph(tree, rel, g)
    else:
        if _ext(rel) not in ("ttl",):
            raise OpError("new files are written as Turtle (.ttl)")
        tree.write(rel, text.strip() + "\n")
    tree.forget(rel)
    return {"triples_added": len(g) - before, "triples_removed": 0, "created": not exists}


def op_remove_triples(tree, args):
    rel = args["file"]
    rows = [triple(r) for r in args.get("triples") or []]
    if not rows:
        raise OpError("nothing to remove")
    g = tree.graph(rel)
    for t in rows:
        if t not in g:
            raise OpError(f"{rel}: the triple {' '.join(n3(x) for x in t)[:160]} is no longer there")
    for t in rows:
        g.remove(t)
    save_graph(tree, rel, g)
    return {"triples_added": 0, "triples_removed": len(rows)}


def op_retype(tree, args):
    rel = args["file"]
    old, new = term(args["from"]), term(args["to"])
    subjects = [term(s) for s in args.get("subjects") or []]
    if not subjects:
        raise OpError("retype lists its subjects one by one")
    g = tree.graph(rel)
    for s in subjects:
        if (s, RDF.type, old) not in g:
            raise OpError(f"{rel}: {n3(s)} is not typed {n3(old)} any more")
    for s in subjects:
        g.remove((s, RDF.type, old))
        g.add((s, RDF.type, new))
    save_graph(tree, rel, g)
    return {"subjects_retyped": len(subjects), "triples_added": len(subjects),
            "triples_removed": len(subjects)}


def bnode_signature(g, node, depth=0):
    if depth > 6:
        return "..."
    parts = []
    for p, o in g.predicate_objects(node):
        o_sig = "[" + bnode_signature(g, o, depth + 1) + "]" if isinstance(o, BNode) else o.n3()
        parts.append(p.n3() + " " + o_sig)
    return ";".join(sorted(parts))


def _drop_bnode(g, node, seen=None):
    seen = seen if seen is not None else set()
    if node in seen:
        return 0
    seen.add(node)
    n = 0
    for p, o in list(g.predicate_objects(node)):
        g.remove((node, p, o))
        n += 1
        if isinstance(o, BNode) and not any(True for _ in g.subjects(None, o)):
            n += _drop_bnode(g, o, seen)
    return n


def duplicate_bnodes(g):
    """[(subject, predicate, [duplicate nodes to drop])] for identical blank nodes."""
    out = []
    for s in sorted(set(g.subjects()), key=n3):
        groups = {}
        for p, o in g.predicate_objects(s):
            if isinstance(o, BNode):
                groups.setdefault((p, bnode_signature(g, o)), []).append(o)
        for (p, _), nodes in sorted(groups.items(), key=lambda x: (n3(x[0][0]), x[0][1])):
            if len(nodes) > 1:
                nodes = sorted(nodes, key=str)
                out.append((s, p, nodes[1:]))
    return out


def op_merge_nodes(tree, args):
    mode = args.get("mode")
    if mode == "bnodes":
        merged = removed = 0
        expect = args.get("expect") or {}
        for rel in args.get("files") or []:
            g = tree.graph(rel)
            dupes = duplicate_bnodes(g)
            n = sum(len(d[2]) for d in dupes)
            if rel in expect and n != expect[rel]:
                raise OpError(f"{rel}: {n} duplicate blank nodes, the preview counted {expect[rel]}")
            if not n:
                continue
            for s, p, nodes in dupes:
                for node in nodes:
                    g.remove((s, p, node))
                    if not any(True for _ in g.subjects(None, node)):
                        removed += _drop_bnode(g, node)
                    merged += 1
            save_graph(tree, rel, g)
        return {"nodes_merged": merged, "triples_added": 0, "triples_removed": 0,
                "duplicate_triples_dropped": removed}
    if mode == "iris":
        mapping = {str(k): str(v) for k, v in (args.get("mapping") or {}).items() if k and v and k != v}
        if not mapping:
            raise OpError("merge_nodes needs a confirmed mapping table")
        total = {}
        for old, new in sorted(mapping.items()):
            r = op_rewrite_iri(tree, {"from": old, "to": new, "mode": "iri",
                                      "files": args.get("files") or []})
            for k, v in r["references_rewritten"].items():
                total[k] = total.get(k, 0) + v
        return {"references_rewritten": total, "triples_added": 0, "triples_removed": 0}
    raise OpError("merge_nodes mode must be 'bnodes' or 'iris'")


def op_write_text(tree, args):
    from .templates import render_text
    rel = args["path"]
    current = tree.read(rel) if tree.exists(rel) else None
    text = render_text(args["template"], args.get("slots") or {}, current)
    if text == current:
        return {"lines_changed": 0, "triples_added": 0, "triples_removed": 0}
    tree.write(rel, text)
    return {"lines_changed": line_delta(current or "", text), "created": current is None,
            "triples_added": 0, "triples_removed": 0}


def op_exclude_file(tree, args):
    rel = args["path"]
    if not tree.exists(rel):
        raise OpError(f"{rel} is not in the release")
    mode = args.get("mode", "drop")
    if mode == "legacy":
        text = tree.read(rel)
        tree.write("legacy/" + rel, text)
    elif mode != "drop":
        raise OpError("exclude_file mode is 'drop' or 'legacy'")
    tree.remove(rel)
    return {"excluded": rel, "moved_to": "legacy/" + rel if mode == "legacy" else None,
            "triples_added": 0, "triples_removed": 0}


def line_delta(a, b):
    return sum(1 for line in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if line[:1] in "+-" and not line.startswith(("+++", "---")))


HANDLERS = {
    "rewrite_iri": op_rewrite_iri, "set_literal": op_set_literal, "add_triples": op_add_triples,
    "remove_triples": op_remove_triples, "retype": op_retype, "merge_nodes": op_merge_nodes,
    "write_text": op_write_text, "exclude_file": op_exclude_file,
}


def run(tree, op, guard=None):
    """Apply one op dict ``{op, args, ...}``; return the counts it produced."""
    name = op.get("op")
    if name not in HANDLERS:
        raise OpError(f"unknown change operation: {name!r}")
    args = op.get("args") or {}
    if name == "add_triples":
        return HANDLERS[name](tree, args, guard)
    return HANDLERS[name](tree, args)
