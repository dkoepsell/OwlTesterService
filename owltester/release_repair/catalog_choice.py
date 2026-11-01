"""Choice remedies (spec 3.4): two or three defensible changes; the user picks."""

import difflib

import rdflib
from rdflib import OWL, RDF, RDFS, XSD, BNode, Literal, URIRef

from ontology_bundle import BFO_IRI_PREFIX
from .catalog import MAX_ROWS, builder, letters, remedy
from .model import RemedyOption
from .ops import n3

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")


def _describe(ctx, t):
    s, p, o = t
    show = (lambda x: ctx.short(x) if isinstance(x, URIRef) else
            ("a blank node" if isinstance(x, BNode) else x.n3()[:80]))
    if p == RDF.type:
        return f"the type {show(o)} on {show(s)}"
    return f"{show(s)} {show(p)} {show(o)}"


@builder("E_ABOX_INCONSISTENT", "E_INCONSISTENT")
def inconsistent(ctx, f):
    ev = f.get("evidence") or {}
    text = ev.get("minimal_triples") or ""
    g = rdflib.Graph()
    try:
        g.parse(data=text, format="turtle")
    except Exception:  # noqa: BLE001
        g = rdflib.Graph()
    opts, it = [], letters()
    paths = set(f.get("files") or [])
    for t in sorted(g, key=lambda t: tuple(n3(x) for x in t))[:8]:
        if any(isinstance(x, BNode) for x in t):
            continue
        where = [p for p in ctx.files_with(t) if (not paths or p in paths) and ctx.writable(p)]
        if not where:
            continue
        opts.append(RemedyOption(
            id=next(it), recommended=False, label=f"Remove {_describe(ctx, t)}",
            consequence=(f"The statement leaves {', '.join(where)}. If it was true, the data now "
                         "says less than it should; check the source before removing it."),
            ops=[{"op": "remove_triples", "args": {"file": p, "triples": [[n3(x) for x in t]]}}
                 for p in where],
            preview={"remove": [n3(x) for x in t], "files": where}))
    types = {o for _, o in g.subject_objects(RDF.type) if isinstance(o, URIRef)}
    for a, b in sorted(ctx.tbox.subject_objects(OWL.disjointWith), key=lambda x: (str(x[0]), str(x[1]))):
        if not (isinstance(a, URIRef) and isinstance(b, URIRef)):
            continue
        if _reaches(ctx.tbox, types, a) and _reaches(ctx.tbox, types, b):
            src = ctx.declaring_file(a, OWL.disjointWith, b)
            if not src or not ctx.writable(src):
                continue
            opts.append(RemedyOption(
                id=next(it),
                label=f"Relax the axiom: drop owl:disjointWith between {ctx.short(a)} and {ctx.short(b)}",
                consequence=(f"Individuals may then be both {ctx.label(a)} and {ctx.label(b)}, and "
                             "the reasoner no longer catches one typed as both by mistake. Every "
                             "other data set loses that check too."),
                ops=[{"op": "remove_triples", "args": {"file": src,
                                                       "triples": [[n3(a), n3(OWL.disjointWith), n3(b)]]}}],
                preview={"remove": [n3(a), n3(OWL.disjointWith), n3(b)], "files": [src]}))
    if not opts:
        return remedy(f, "guided", "Resolve the contradiction",
                      "The data and the ontology cannot both be true.", [],
                      explanation=(f.get("message") or "") + "\n\nMinimal cause:\n" + text)
    return remedy(f, "choice", "Resolve the contradiction",
                  "A contradiction makes every inference from the data meaningless: a reasoner "
                  "can then derive anything.", opts, explanation="Minimal cause:\n" + text)


def _reaches(g, starts, target, limit=200):
    seen, todo = set(), list(starts)
    while todo and len(seen) < limit:
        c = todo.pop()
        if c == target:
            return True
        if c in seen:
            continue
        seen.add(c)
        todo.extend(o for o in g.objects(c, RDFS.subClassOf) if isinstance(o, URIRef))
    return False


@builder("E_UNSAT", "E_DISJOINT")
def straddle(ctx, f):
    c = URIRef(f.get("iri") or "")
    supers = sorted({o for o in ctx.tbox.objects(c, RDFS.subClassOf) if isinstance(o, URIRef)}, key=str)
    bfo = [s for s in supers if str(s).lower().startswith(BFO_IRI_PREFIX)]
    candidates = bfo if len(bfo) >= 2 else supers if len(supers) >= 2 else []
    opts, it = [], letters()
    for drop in candidates:
        keep = [s for s in candidates if s != drop]
        src = ctx.declaring_file(c, RDFS.subClassOf, drop)
        if not src or not ctx.writable(src):
            continue
        opts.append(RemedyOption(
            id=next(it), label=f"Keep {', '.join(ctx.label(k) for k in keep)}; drop {ctx.label(drop)}",
            consequence=(f"{ctx.label(c)} stops being a {ctx.label(drop)}. Anything that relied on "
                         f"that (queries, inherited restrictions) no longer applies to it."),
            ops=[{"op": "remove_triples", "args": {"file": src,
                                                   "triples": [[n3(c), n3(RDFS.subClassOf), n3(drop)]]}}],
            preview={"remove": [n3(c), n3(RDFS.subClassOf), n3(drop)], "files": [src]}))
    if not opts:
        return remedy(f, "guided", f"Make {ctx.label(c)} satisfiable",
                      "A class no individual can belong to is a modeling error.", [],
                      explanation=f.get("message", ""))
    return remedy(f, "choice", f"Keep one category for {ctx.label(c)}",
                  "A class under two disjoint categories can have no instances.", opts)


def _similar(ctx, iri, limit=3):
    from ..audit.references import declared_terms
    target = str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
    scored = []
    for d in declared_terms(ctx.art):
        if str(d) == str(iri) or not ctx.art.is_owned(d):
            continue
        name = str(d).rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
        lab = str(ctx.tbox.value(d, RDFS.label) or "").lower().replace(" ", "")
        score = max(difflib.SequenceMatcher(None, target, name).ratio(),
                    difflib.SequenceMatcher(None, target, lab).ratio() if lab else 0)
        if score >= 0.6:
            scored.append((score, str(d)))
    return sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]


def _guess_type(ctx, iri):
    for f in ctx.rdf():
        g = f.graph
        if (None, RDF.type, iri) in g:
            return OWL.Class
        objs = list(g.objects(None, iri))
        if objs:
            return OWL.DatatypeProperty if all(isinstance(o, Literal) for o in objs[:20]) \
                else OWL.ObjectProperty
    return OWL.NamedIndividual


@builder("E_UNDECLARED_TERM")
def undeclared(ctx, f):
    iri = URIRef(f.get("iri") or "")
    uses = {p: n for p, n in ctx.ref_counts(str(iri), "iri").items() if ctx.writable(p)}
    opts, it = [], letters()
    for score, d in _similar(ctx, iri):
        opts.append(RemedyOption(
            id=next(it), recommended=not opts,
            label=f"Map it to {ctx.short(d)} (similarity {score:.2f})",
            consequence=f"{sum(uses.values())} use(s) in {len(uses)} file(s) point at the declared "
                        f"term {ctx.label(d)} instead.",
            ops=[{"op": "rewrite_iri", "args": {"from": str(iri), "to": d, "mode": "iri",
                                                "files": sorted(uses), "expect": uses}}],
            preview={"counts": uses}))
    target = next((x.path for x in ctx.rdf(("ontology", "vocabulary")) if ctx.writable(x.path)
                   and any(str(s).startswith(str(iri).rsplit("#", 1)[0].rsplit("/", 1)[0])
                           for s in x.graph.subjects())), None)
    if target:
        kind = _guess_type(ctx, iri)
        local = str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        draft = (f"<{iri}> a <{kind}> ;\n    <{RDFS.label}> \"{local}\"@en ;\n"
                 f"    <{RDFS.comment}> \"Describe what {local} means.\"@en .\n")
        opts.append(RemedyOption(
            id=next(it), recommended=not opts, label=f"Declare it in {target}",
            consequence="The term becomes part of the vocabulary. Complete the draft: a label and "
                        "a definition, at least.",
            ops=[{"op": "add_triples", "args": {"file": target, "turtle": "{{content}}"}}],
            input={"kind": "turtle", "label": "Declaration", "default": draft}))
    rows = []
    for p in sorted(uses):
        g = ctx.art.get(p).graph
        ts = [t for t in g if iri in t and not any(isinstance(x, BNode) for x in t)]
        if ts:
            rows.append((p, ts))
    if rows:
        n = sum(len(ts) for _, ts in rows)
        opts.append(RemedyOption(
            id=next(it), label="Remove its uses",
            consequence=f"{n} statement(s) that use it leave the data. Only choose this if they "
                        "are noise; the removal bound still applies.",
            ops=[{"op": "remove_triples", "args": {"file": p, "triples": [[n3(x) for x in t] for t in ts]}}
                 for p, ts in rows],
            preview={"counts": {p: len(ts) for p, ts in rows}}))
    if not opts:
        return None
    return remedy(f, "choice", f"Resolve the undeclared term {ctx.short(iri)}",
                  "A term no vocabulary declares has no definition, so nobody can tell what the "
                  "data means by it.", opts)


@builder("E_DATATYPE_PROFILE")
def datatype_profile(ctx, f):
    ev = f.get("evidence") or {}
    props = {}
    for qn, dts in (ev.get("properties") or {}).items():
        p = ctx.expand(qn)
        bad = [ctx.expand(d) for d in dts]
        if p is not None:
            props[p] = [b for b in bad if b is not None]
    if not props:
        return None
    a_ops, b_ops, lits = [], [], 0
    for p, bad in sorted(props.items(), key=lambda x: str(x[0])):
        for dt in bad:
            src = ctx.declaring_file(p, RDFS.range, dt)
            if src and ctx.writable(src):
                a_ops += [{"op": "remove_triples", "args": {"file": src, "triples": [[n3(p), n3(RDFS.range), n3(dt)]]}},
                          {"op": "add_triples", "args": {"file": src, "triples": [[n3(p), n3(RDFS.range), n3(XSD.string)]]}}]
                b_ops += [{"op": "remove_triples", "args": {"file": src, "triples": [[n3(p), n3(RDFS.range), n3(dt)]]}}]
                if (p, RDF.type, OWL.DatatypeProperty) in ctx.art.get(src).graph:
                    b_ops.append({"op": "retype", "args": {"file": src, "subjects": [n3(p)],
                                                           "from": n3(OWL.DatatypeProperty),
                                                           "to": n3(OWL.AnnotationProperty)}})
        for df in ctx.rdf(("data", "shapes")):
            changes = [[n3(s), n3(p), n3(o), n3(Literal(str(o), datatype=XSD.string))]
                       for s, o in df.graph.subject_objects(p)
                       if isinstance(o, Literal) and o.datatype in bad and not isinstance(s, BNode)]
            if changes and ctx.writable(df.path):
                a_ops.append({"op": "set_literal", "args": {"file": df.path, "changes": changes}})
                lits += len(changes)
    if not a_ops:
        return None
    names = ", ".join(ctx.short(p) for p in props)
    opts = [RemedyOption(
        id="a", recommended=True, label=f"Use xsd:string for {names}",
        consequence=("Reasoners can load the ontology. Values keep their text but lose their "
                     f"datatype ({lits} literal(s) retyped); add a sh:pattern shape if the format "
                     "should still be checked."),
        ops=a_ops, preview={"properties": sorted(map(str, props)), "literals": lits})]
    if b_ops:
        opts.append(RemedyOption(
            id="b", label=f"Make {names} annotation properties",
            consequence=("The values become documentation for reasoners: nothing is checked or "
                         "inferred from them, and SHACL remains the only check."),
            ops=b_ops))
    return remedy(f, "choice", "Use datatypes reasoners understand",
                  "Datatypes outside the OWL 2 map stop standard reasoners from loading the "
                  "ontology at all.", opts,
                  explanation="For durations and intervals, OWL-Time (time:Duration with "
                              "time:numericDuration and time:unitType) models the value as a "
                              "resource instead of a literal. That is a modeling change: plan it "
                              "as a new module rather than a repair.")


def _property_shapes(ctx, c, p):
    """[(shapes file, canonical node, its triples)] for property shapes on (class, path)."""
    out = []
    for sf in ctx.rdf(("shapes",)):
        if not ctx.writable(sf.path):
            continue
        g = ctx.canonical(sf.path)
        targets = {c} | {a for a in ctx.tbox.transitive_objects(c, RDFS.subClassOf)}
        for ns in g.subjects(SH.targetClass, None):
            if g.value(ns, SH.targetClass) not in targets:
                continue
            for ps in g.objects(ns, SH.property):
                if g.value(ps, SH.path) == p:
                    out.append((sf.path, ps, g))
        for ps in g.subjects(SH.path, p):
            if (ps, RDF.type, SH.NodeShape) in g and g.value(ps, SH.targetClass) in targets:
                out.append((sf.path, ps, g))
    return out


def _restrictions(ctx, c, p):
    out = []
    for of in ctx.rdf(("ontology",)):
        if not ctx.writable(of.path):
            continue
        g = ctx.canonical(of.path)
        for r in g.objects(c, RDFS.subClassOf):
            if isinstance(r, BNode) and g.value(r, OWL.onProperty) == p:
                rows = [[n3(c), n3(RDFS.subClassOf), n3(r)]] + \
                    [[n3(r), n3(x), n3(y)] for x, y in g.predicate_objects(r)]
                out.append((of.path, rows))
    return out


@builder("E_LAYER_CONFLICT")
def layer_conflict(ctx, f):
    ev = f.get("evidence") or {}
    owl = ev.get("owl") or {}
    title = f.get("title", "")
    c = ctx.expand(title.split(" / ")[0]) if " / " in title else None
    p = URIRef(f.get("iri") or "")
    if c is None:
        return None
    opts, it = [], letters()
    shapes = _property_shapes(ctx, c, p)
    a_ops = []
    for path, ps, g in shapes:
        for key, pred in (("min", SH.minCount), ("max", SH.maxCount)):
            if owl.get(key) is None:
                continue
            old = g.value(ps, pred)
            new = Literal(int(owl[key]))
            if old is not None and old == new:
                continue
            if old is not None:
                a_ops.append({"op": "remove_triples", "args": {"file": path, "triples": [[n3(ps), n3(pred), n3(old)]]}})
            a_ops.append({"op": "add_triples", "args": {"file": path,
                                                        "triples": [[n3(ps), n3(pred), n3(new)]]}})
    if a_ops:
        opts.append(RemedyOption(
            id=next(it), recommended=True, label="Make OWL authoritative: align the shape",
            consequence=(f"The shape for {ctx.short(p)} on {ctx.short(c)} now checks what the axiom "
                         f"says (min {owl.get('min', 0)}, max {owl.get('max', 'none')}). Data that "
                         "omitted the value now fails validation instead of passing silently."),
            ops=a_ops))
    rs = _restrictions(ctx, c, p)
    if rs:
        opts.append(RemedyOption(
            id=next(it), label="Make SHACL authoritative: remove the OWL restriction",
            consequence=(f"The OWL restriction on {ctx.short(p)} for {ctx.short(c)} is removed, so a "
                         "reasoner no longer expects it; only the shape checks the data."),
            ops=[{"op": "remove_triples", "args": {"file": path, "triples": rows}} for path, rows in rs],
            preview={"remove": [r for _, rows in rs for r in rows][:12]}))
    if not opts:
        return None
    return remedy(f, "choice", f"Make the layers agree on {ctx.short(c)} / {ctx.short(p)}",
                  "When OWL, SHACL and the text disagree, tools and people each enforce a different "
                  "rule.", opts,
                  explanation="To align both to the documentation instead, decide here and edit the "
                              "text so it says the same thing.")


@builder("W_UNENFORCED")
def unenforced(ctx, f):
    title = f.get("title", "")
    c = ctx.expand(title.split(" / ")[0]) if " / " in title else None
    p = URIRef(f.get("iri") or "")
    shapes = [x for x in ctx.rdf(("shapes",)) if ctx.writable(x.path)]
    if c is None or not shapes:
        return None
    sf = shapes[0]
    node = next((s for s in sf.graph.subjects(SH.targetClass, c) if isinstance(s, URIRef)), None)
    if node is not None:
        snippet = f"<{node}> <{SH.property}> [ <{SH.path}> <{p}> ; <{SH.minCount}> 1 ] .\n"
    else:
        base = str(c) + "Shape"
        snippet = (f"<{base}> a <{SH.NodeShape}> ;\n    <{SH.targetClass}> <{c}> ;\n"
                   f"    <{SH.property}> [ <{SH.path}> <{p}> ; <{SH.minCount}> 1 ] .\n")
    opt = RemedyOption(id="a", recommended=True, label=f"Generate the missing shape in {sf.path}",
                       consequence=f"Data that leaves out {ctx.short(p)} on a {ctx.label(c)} now fails "
                                   "validation, as the documentation says it should.",
                       ops=[{"op": "add_triples", "args": {"file": sf.path, "turtle": snippet}}],
                       preview={"turtle": snippet})
    return remedy(f, "choice", f"Enforce what the documentation requires of {ctx.short(c)}",
                  "A requirement nothing enforces is a suggestion.", [opt],
                  explanation="If the requirement is too strong, soften the documentation instead "
                              "(MUST to SHOULD) and skip this card with a note.")


@builder("W_SUBCLASS_COLLAPSE")
def subclass_collapse(ctx, f):
    c = URIRef(f.get("iri") or "")
    ds = (f.get("evidence") or {}).get("data_set")
    subs = [ctx.expand(x) for x in (f.get("evidence") or {}).get("subclasses", [])]
    subs = [s for s in subs if s is not None]
    rows = []
    for df in ctx.rdf(("data",)):
        if ds is not None and df.data_set != ds or not ctx.writable(df.path):
            continue
        for s in sorted(df.graph.subjects(RDF.type, c), key=str):
            if isinstance(s, URIRef):
                lab = df.graph.value(s, RDFS.label) or df.graph.value(s, URIRef("http://purl.org/dc/terms/title"))
                rows.append({"subject": str(s), "file": df.path, "label": str(lab or "")[:120], "choice": ""})
            if len(rows) >= MAX_ROWS:
                break
    if not rows or not subs:
        return None
    opt = RemedyOption(
        id="a", recommended=True, label="Pick the specific subclass for each instance",
        consequence=("Each instance you assign is retyped from the general class to the subclass; "
                     "rows left blank keep the general class."),
        input={"kind": "table", "column": "choice", "rows": rows,
               "choices": [{"iri": str(s), "label": ctx.label(s)} for s in subs]},
        ops=[{"op": "retype", "args": {"from": n3(c), "table": True}}])
    return remedy(f, "choice", f"Use the subclasses of {ctx.short(c)}",
                  "Data typed only with the general class hides the distinctions the ontology draws.",
                  [opt], explanation="If the general class is what the data means, declare the outcome "
                                     "expected instead, with your reason.")


@builder("W_PLACEHOLDER_IRI")
def placeholders(ctx, f):
    ev = f.get("evidence") or {}
    hosts = list((ev.get("by_host") or {}).keys())
    ds = ev.get("data_set")
    files = [x.path for x in ctx.rdf(("data",)) if (ds is None or x.data_set == ds) and ctx.writable(x.path)]
    prefixes = sorted({f"{scheme}://{h}/" for h in hosts for scheme in ("http", "https")})
    counts = {}
    for p in files:
        g = ctx.art.get(p).graph
        n = sum(1 for t in g for x in (t[0], t[2])
                if isinstance(x, URIRef) and any(str(x).startswith(pre) for pre in prefixes))
        if n:
            counts[p] = n
    if not counts:
        return None
    ops = [{"op": "rewrite_iri", "args": {"from": pre, "to": "{{value}}", "mode": "namespace",
                                          "files": sorted(counts)}} for pre in prefixes]
    opt = RemedyOption(id="a", recommended=True, label="Map the placeholder host to a real base IRI",
                       consequence=(f"{sum(counts.values()):,} IRIs in {len(counts)} file(s) move to "
                                    "the base you give. Choose a base you control and will keep "
                                    "resolvable."),
                       ops=ops, preview={"counts": counts, "hosts": hosts},
                       input={"kind": "iri", "label": "Base IRI (ending in / or #)", "default": ""})
    return remedy(f, "choice", "Replace placeholder IRIs", "Placeholder hosts cannot be linked or "
                  "deduplicated, and they clash with every other release that uses them.", [opt],
                  explanation="If these are examples or tests, declare the outcome expected instead.")
