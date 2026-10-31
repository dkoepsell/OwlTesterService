"""R6: what OWL, SHACL and the documentation each say about one (class, property).

OWL: cardinalities, someValuesFrom (min 1), functional (max 1), allValuesFrom,
range datatype. SHACL: minCount, maxCount, sh:in, sh:class, sh:datatype.
Documentation: requirement words in annotations, and in the source's own
comments next to an axiom (read from the raw Turtle text). Constraints on a
superclass apply to shapes that target its subclasses.
"""

import re
from collections import defaultdict

from rdflib import OWL, RDF, RDFS, XSD, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SKOS

from .. import errors
from .artifact import SH
from .schema_checks import local, qname

DOC_PREDICATES = (RDFS.comment, SKOS.scopeNote, SKOS.definition,
                  URIRef("http://purl.org/dc/terms/description"))
REQUIRED = re.compile(r"\bMUST\b(?!\s+(NOT|use values))|\b(is|are)\s+(mandatory|required)\b"
                      r"|\bexactly one\b|\bat least one\b")
FORBIDDEN = re.compile(r"\bMUST NOT\b|\bmust not\b")
VALUES = re.compile(r"\bMUST use values from\b", re.I)


def _kind(text):
    if FORBIDDEN.search(text):
        return "forbidden"
    if VALUES.search(text):
        return "values"
    if REQUIRED.search(text):
        return "required"
    return None
TODO = re.compile(r"#.*\b(TODO|FIXME)\b[:\s]*(.*)", re.I)
SUBJECT_LINE = re.compile(r"^([^\s#@][^\s]*)\s")
ON_PROPERTY = re.compile(r"owl:onProperty\s+(\S+?)\s*[;\]]?\s*$")


def _int(node):
    try:
        return int(node)
    except (TypeError, ValueError):
        return None


def owl_layer(g):
    """(class, property) -> {min, max, values, class, datatype} from OWL."""
    out = defaultdict(dict)
    for c, r in list(g.subject_objects(RDFS.subClassOf)) + list(g.subject_objects(OWL.equivalentClass)):
        if not isinstance(c, URIRef):
            continue
        p = g.value(r, OWL.onProperty)
        if not isinstance(p, URIRef):
            continue
        rec = out[(c, p)]
        for pred in (OWL.minCardinality, OWL.minQualifiedCardinality):
            if _int(g.value(r, pred)) is not None:
                rec["min"] = max(rec.get("min", 0), _int(g.value(r, pred)))
        for pred in (OWL.cardinality, OWL.qualifiedCardinality):
            if _int(g.value(r, pred)) is not None:
                rec["min"] = rec["max"] = _int(g.value(r, pred))
        for pred in (OWL.maxCardinality, OWL.maxQualifiedCardinality):
            if _int(g.value(r, pred)) is not None:
                rec["max"] = _int(g.value(r, pred))
        if g.value(r, OWL.someValuesFrom) is not None:
            rec["min"] = max(rec.get("min", 0), 1)
        avf = g.value(r, OWL.allValuesFrom)
        if avf is not None:
            lst = g.value(avf, OWL.oneOf)
            if lst is not None:
                rec["values"] = sorted(str(x) for x in Collection(g, lst))
            elif isinstance(avf, URIRef):
                rec["class"] = str(avf)
    for p in g.subjects(RDF.type, OWL.FunctionalProperty):
        for c in g.objects(p, RDFS.domain):
            if isinstance(c, URIRef):
                out[(c, p)].setdefault("max", 1)
    return out


def shacl_layer(g):
    out = defaultdict(list)
    for shape in set(g.subjects(RDF.type, SH.NodeShape)):
        targets = [t for t in g.objects(shape, SH.targetClass) if isinstance(t, URIRef)]
        if (shape, RDF.type, OWL.Class) in g or (shape, RDF.type, RDFS.Class) in g:
            targets.append(shape)
        for ps in g.objects(shape, SH.property):
            p = g.value(ps, SH.path)
            if not isinstance(p, URIRef):
                continue
            rec = {"min": _int(g.value(ps, SH.minCount)), "max": _int(g.value(ps, SH.maxCount)),
                   "explicit_min": g.value(ps, SH.minCount) is not None}
            lst = g.value(ps, SH["in"])
            if lst is not None:
                rec["values"] = sorted(str(x) for x in Collection(g, lst))
            if g.value(ps, SH["class"]) is not None:
                rec["class"] = str(g.value(ps, SH["class"]))
            if g.value(ps, SH.datatype) is not None:
                rec["datatype"] = str(g.value(ps, SH.datatype))
            for t in targets:
                out[(t, p)].append(rec)
    return out


def source_comments(files):
    """Requirement words and TODOs in Turtle comments, tied to (subject, property)."""
    found = []
    for f in files:
        try:
            lines = f.text().splitlines()
        except OSError:
            continue
        nm = f.graph.namespace_manager
        subject = None
        for i, line in enumerate(lines):
            m = SUBJECT_LINE.match(line)
            if m and not line.startswith(("PREFIX", "BASE")):
                subject = m.group(1)
            code = re.sub(r'"[^"]*"|<[^>]*>', "", line)   # '#' inside IRIs and strings is not a comment
            if "#" not in code:
                continue
            comment = code[code.index("#"):]
            todo = TODO.search(comment)
            kind = _kind(comment)
            if not (todo or kind):
                continue
            prop = None
            for nxt in lines[i + 1:i + 8]:
                pm = ON_PROPERTY.search(nxt.strip())
                if pm:
                    prop = pm.group(1)
                    break
                if SUBJECT_LINE.match(nxt):
                    break
            found.append({"file": f.path, "line": i + 1, "text": comment.lstrip("# ").strip(),
                          "subject": _expand(nm, subject), "property": _expand(nm, prop),
                          "todo": bool(todo), "kind": kind})
    return found


def _expand(nm, token):
    if not token:
        return None
    token = token.rstrip(";,.")
    if token.startswith("<") and token.endswith(">"):
        return token[1:-1]
    try:
        return str(nm.expand_curie(token))
    except Exception:  # noqa: BLE001
        return None


def doc_layer(g, comments):
    out = defaultdict(list)
    domains = defaultdict(set)
    for p, c in g.subject_objects(RDFS.domain):
        if isinstance(c, URIRef):
            domains[p].add(c)
    props = {p for p in g.subjects(RDF.type, None) if isinstance(p, URIRef)
             and ((p, RDF.type, OWL.ObjectProperty) in g or (p, RDF.type, OWL.DatatypeProperty) in g)}
    for subj, pred, lit in g.triples((None, None, None)):
        if pred not in DOC_PREDICATES or not isinstance(lit, Literal) or not isinstance(subj, URIRef):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n", str(lit)):
            kind = _kind(sentence)
            if not kind:
                continue
            if subj in props:
                for c in domains.get(subj, ()):
                    out[(c, subj)].append({"text": sentence.strip()[:240], "kind": kind,
                                           "where": f"{local(pred)} of {qname(g, subj)}"})
            else:
                # only distinctive names: a property called "in" or "of" is not mentioned
                # every time the word appears
                for p in props:
                    name = local(p)
                    if (len(name) >= 6 or re.search(r"[a-z][A-Z]", name)) and \
                            re.search(rf"\b{re.escape(name)}\b", sentence):
                        out[(subj, p)].append({"text": sentence.strip()[:240], "kind": kind,
                                               "where": f"{local(pred)} of {qname(g, subj)}"})
    for c in comments:
        if c["kind"] and c["subject"] and c["property"]:
            out[(URIRef(c["subject"]), URIRef(c["property"]))].append(
                {"text": c["text"][:240], "kind": c["kind"],
                 "where": f"comment at {c['file']}:{c['line']}"})
    return out


def _ancestors(g, c):
    seen, todo = {c}, [c]
    while todo:
        for p in g.objects(todo.pop(), RDFS.subClassOf):
            if isinstance(p, URIRef) and p not in seen:
                seen.add(p)
                todo.append(p)
    return seen


def run_r6(ctx):
    art = ctx.artifact
    onto_files = art.by_role("ontology")
    if not onto_files:
        ctx.skip("R6", "Constraint layers", "No ontology file in the artifact.")
        return
    tbox = art.tbox()
    shapes = art.shapes_graph()
    owl = owl_layer(tbox)
    sh = shacl_layer(shapes)
    comments = source_comments(onto_files + art.by_role("shapes"))
    docs = doc_layer(tbox, comments)
    ranges = {p: str(o) for p, o in tbox.subject_objects(RDFS.range) if str(o).startswith(str(XSD))}

    def owl_for(c, p):
        merged = {}
        for a in _ancestors(tbox, c):
            for k, v in owl.get((a, p), {}).items():
                merged.setdefault(k, v)
        if p in ranges:
            merged.setdefault("datatype", ranges[p])
        return merged

    def doc_for(c, p):
        return [d for a in _ancestors(tbox, c) for d in docs.get((a, p), [])]

    conflicts, pairs = 0, set(sh) | set(owl) | set(docs)
    files = [f.path for f in onto_files] + [f.path for f in art.by_role("shapes")]
    for (c, p) in sorted(pairs, key=lambda x: (str(x[0]), str(x[1]))):
        if not art.is_owned(c):
            continue
        o, shs, ds = owl_for(c, p), sh.get((c, p), []), doc_for(c, p)
        problems = []
        for s in shs:
            smin = s["min"] if s["min"] is not None else 0
            if o.get("min", 0) > smin and (s["explicit_min"] or s.get("max") is not None):
                problems.append(f"OWL requires at least {o['min']}, SHACL sh:minCount is {smin}")
            if o.get("max") is not None and s.get("max") is not None and o["max"] != s["max"]:
                problems.append(f"OWL allows at most {o['max']}, SHACL sh:maxCount is {s['max']}")
            if "values" in o and "values" in s and set(o["values"]) != set(s["values"]):
                problems.append("OWL and SHACL list different allowed values")
            if "datatype" in o and "datatype" in s and o["datatype"] != s["datatype"]:
                problems.append(f"OWL range is {qname(tbox, o['datatype'])}, SHACL sh:datatype is "
                                f"{qname(tbox, s['datatype'])}")
            if any(d["kind"] == "required" for d in ds) and s["explicit_min"] and smin == 0:
                problems.append("the documentation says it is required, SHACL sh:minCount is 0")
            if any(d["kind"] == "forbidden" for d in ds) and smin > 0:
                problems.append("the documentation forbids it, SHACL requires it")
        if any(d["kind"] == "forbidden" for d in ds) and o.get("min", 0) > 0:
            problems.append("the documentation forbids it, OWL requires it")
        todos = [t for t in comments if t["todo"] and t["subject"] == str(c)
                 and t["property"] in (None, str(p))]
        if problems:
            conflicts += 1
            ctx.add("R6", errors.E_LAYER_CONFLICT, "major",
                    f"{qname(tbox, c)} / {qname(tbox, p)}: the layers disagree",
                    "; ".join(dict.fromkeys(problems)) + ".", iri=str(p), files=files,
                    evidence={"owl": o, "shacl": shs, "documentation": ds,
                              "todo": [f"{t['file']}:{t['line']} {t['text']}" for t in todos]},
                    fix="Decide the intended cardinality and make OWL, SHACL and the text say the "
                        "same thing.")
        else:
            anc_shapes = [s for a in _ancestors(tbox, c) for s in sh.get((a, p), [])]
            required = [d for d in ds if d["kind"] == "required"]
            values = [d for d in ds if d["kind"] == "values"]
            if required and o.get("min", 0) == 0 and not any((s["min"] or 0) > 0 for s in anc_shapes):
                ctx.add("R6", errors.W_UNENFORCED, "minor",
                        f"{qname(tbox, c)} / {qname(tbox, p)}: documented as required, never enforced",
                        "No OWL axiom and no SHACL shape requires it.", iri=str(p), files=files,
                        evidence={"documentation": required},
                        fix="Add sh:minCount 1 to the shape (and, if it is part of the model, an "
                            "OWL minCardinality).")
            elif values and not ({"values", "class"} & set(o)) and \
                    not any({"values", "class"} & set(s) for s in anc_shapes) and \
                    (c, p) in docs:
                ctx.add("R6", errors.W_UNENFORCED, "minor",
                        f"{qname(tbox, c)} / {qname(tbox, p)}: documented value list never enforced",
                        "The text names the allowed values, but no allValuesFrom, sh:in or "
                        "sh:class checks them.", iri=str(p), files=files,
                        evidence={"documentation": values},
                        fix="Add sh:in (or sh:class with the concept scheme) to the property shape.")
    todos = [t for t in comments if t["todo"]]
    if todos:
        ctx.add("R6", errors.W_TODO, "info", f"{len(todos)} open TODO or FIXME comment(s) in the source",
                "They mark modeling decisions the release has not settled.",
                files=sorted({t["file"] for t in todos}), count=len(todos),
                evidence={"comments": [{"at": f"{t['file']}:{t['line']}", "text": t["text"],
                                        "subject": qname(tbox, t["subject"]) if t["subject"] else None,
                                        "property": qname(tbox, t["property"]) if t["property"] else None}
                                       for t in todos[:30]]})
    ctx.finish("R6", "Constraint layers: OWL, SHACL, documentation",
               summary=f"{conflicts} (class, property) pairs where the layers disagree; "
                       f"{len(ctx.stage_findings('R6')) - conflicts - (1 if todos else 0)} documented "
                       f"requirements never enforced; {len(todos)} TODO/FIXME comments.")
