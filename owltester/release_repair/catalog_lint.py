"""Design-lint remedies (W_LINT_*): add the axiom the lint suggests, or dismiss it."""

import rdflib
from rdflib import OWL, RDF, RDFS, BNode
from rdflib.collection import Collection

from .catalog import builder, remedy, turtle
from .model import RemedyOption
from .ops import n3


@builder("W_LINT_INVERSE", "W_LINT_TRANSITIVE", "W_LINT_DISJOINT", "W_LINT_ONEOF_UNA")
def lint_add(ctx, f):
    ev = f.get("evidence") or {}
    triples, label = [], ""
    g = rdflib.Graph()
    if f["code"] == "W_LINT_INVERSE":
        for a, b in ev.get("pairs") or []:
            a, b = ctx.expand(a), ctx.expand(b)
            if a is not None and b is not None:
                triples.append((a, OWL.inverseOf, b))
        label = "Declare the pairs inverse (owl:inverseOf)"
    elif f["code"] == "W_LINT_TRANSITIVE":
        for p in ev.get("properties") or []:
            p = ctx.expand(p)
            if p is not None:
                triples.append((p, RDF.type, OWL.TransitiveProperty))
        label = "Declare them transitive"
    elif f["code"] == "W_LINT_DISJOINT":
        for a, b in ev.get("class_and_type_pairs") or []:
            a, b = ctx.expand(a), ctx.expand(b)
            if a is not None and b is not None:
                triples.append((a, OWL.disjointWith, b))
        for grp in ev.get("sibling_groups") or []:
            kids = [ctx.expand(k) for k in grp.get("children", [])]
            if all(k is not None for k in kids) and len(kids) >= 2:
                node = BNode()
                lst = BNode()
                Collection(g, lst, kids)
                triples += [(node, RDF.type, OWL.AllDisjointClasses), (node, OWL.members, lst)] + list(g)
                g = rdflib.Graph()
        label = "Declare the siblings disjoint"
    else:
        for r in ev.get("restrictions") or []:
            vals = [ctx.expand(v) for v in r.get("values", [])]
            if all(v is not None for v in vals) and len(vals) >= 2:
                node, lst = BNode(), BNode()
                Collection(g, lst, vals)
                triples += [(node, RDF.type, OWL.AllDifferent), (node, OWL.distinctMembers, lst)] + list(g)
                g = rdflib.Graph()
        label = "Declare the listed individuals distinct (owl:AllDifferent)"
    target = next((x.path for x in ctx.rdf(("ontology",)) if ctx.writable(x.path)), None)
    if not triples or target is None:
        return None
    snippet = turtle(triples, ctx)
    opt = RemedyOption(id="a", recommended=True, label=label,
                       consequence="The reasoner can now infer and reject more. Check each line: an "
                                   "axiom that is not true of the domain makes valid data inconsistent.",
                       ops=[{"op": "add_triples", "args": {"file": target, "turtle": "{{content}}"}}],
                       input={"kind": "turtle", "label": "Axioms to add (edit or delete lines)",
                              "default": snippet},
                       preview={"turtle": snippet})
    return remedy(f, "choice", f.get("title", label), f.get("message", ""), [opt],
                  explanation="Dismiss with a note (skip) if the names only look related.")


@builder("W_LINT_FOREIGN_AXIOM")
def lint_foreign(ctx, f):
    rows = {}
    for a in (f.get("evidence") or {}).get("axioms") or []:
        p, c = ctx.expand(a.get("property")), ctx.expand(a.get("class"))
        pred = RDFS.domain if a.get("axiom") == "domain" else RDFS.range
        if p is None or c is None:
            continue
        src = ctx.declaring_file(p, pred, c, roles=("ontology",))
        if src and ctx.writable(src):
            rows.setdefault(src, []).append([n3(p), n3(pred), n3(c)])
    if not rows:
        return None
    opt = RemedyOption(id="a", label="Remove the domain and range axioms on properties you do not own",
                       consequence=("Other people's data that uses these properties is no longer "
                                    "retyped. Add a local subproperty or a shape if you still want "
                                    "the constraint for your own data."),
                       ops=[{"op": "remove_triples", "args": {"file": p, "triples": r}} for p, r in rows.items()],
                       preview={"counts": {p: len(r) for p, r in rows.items()}})
    return remedy(f, "choice", "Stop retyping other vocabularies' data", f.get("message", ""), [opt])


@builder("W_LINT_NO_CHARACTERISTICS")
def lint_characteristics(ctx, f):
    from .. import counts
    target = next((x.path for x in ctx.rdf(("ontology",)) if ctx.writable(x.path)), None)
    onto = ctx.art.ontology_graph()
    props = sorted(p for p in counts.object_properties(onto) if ctx.art.is_owned(p))[:12]
    if target is None or not props:
        return None
    draft = "".join(f"# <{p}> a <{OWL.FunctionalProperty}> .\n" for p in props)
    opt = RemedyOption(id="a", label=f"Declare characteristics in {target}",
                       consequence="Only declare what is true of every use: a functional property "
                                   "with two values makes the data inconsistent.",
                       ops=[{"op": "add_triples", "args": {"file": target, "turtle": "{{content}}"}}],
                       input={"kind": "turtle", "label": "Uncomment and adjust the lines that hold",
                              "default": draft})
    return remedy(f, "guided", "Declare the property characteristics the model implies",
                  f.get("message", ""), [opt])
