"""R8: the questions a reviewer asks of shipped data.

Feature use per data set, subclass collapse, unused controlled values,
placeholder IRIs, identity fragmentation, duplicate blank nodes and
domain-driven retyping. Informational unless stated.
"""

import re
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SKOS

from .. import counts, errors
from .artifact import SH, split_iri
from .references import variants
from .schema_checks import local, qname

AGENTISH = re.compile(r"agent|actor|party|addressee|addresser|authority|body|organi[sz]ation|"
                      r"institution|holder|beneficiar|person|entity|stakeholder", re.I)
STOP = {"the", "of", "and", "or", "for", "in", "on", "to", "a", "an", "eu", "agent", "role",
        "example", "org", "com", "http", "https", "www", "member", "states", "state"}
COMPOUND = re.compile(r"(?:_|\b|(?<=[a-z]))(and|or|And|Or)(?=_|[A-Z]|\b)|[A-Za-z]-[A-Z]")


def _words(text):
    text = unquote(text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP]


def _host(iri):
    try:
        return (urlparse(str(iri)).hostname or "").lower()
    except ValueError:
        return ""


def _signature(g, node, depth=0):
    if not isinstance(node, BNode) or depth > 6:
        return node.n3() if not isinstance(node, BNode) else "_"
    return "[" + ";".join(sorted(f"{p.n3()} {_signature(g, o, depth + 1)}"
                                 for p, o in g.predicate_objects(node))) + "]"


def _controlled_values(art):
    """Values a data set is expected to draw from: primary vocabulary concepts,
    owl:oneOf members and sh:in members."""
    out = {}
    for f in art.by_role("vocabulary"):
        for c in f.graph.subjects(RDF.type, SKOS.Concept):
            if isinstance(c, URIRef):
                out[c] = f.path
    for g, where in ((art.tbox(), "owl:oneOf"), (art.shapes_graph(), "sh:in")):
        pred = OWL.oneOf if where == "owl:oneOf" else SH["in"]
        for lst in g.objects(None, pred):
            try:
                for x in Collection(g, lst):
                    if isinstance(x, URIRef):
                        out.setdefault(x, where)
            except Exception:  # noqa: BLE001 - malformed list
                pass
    return out


def run_r8(ctx):
    art = ctx.artifact
    if not art.data_sets:
        ctx.skip("R8", "Data profile", "The artifact ships no data files.")
        return
    tbox = art.tbox()
    onto = art.ontology_graph()
    classes = sorted(c for c in counts.named_classes(onto) if art.is_owned(c))
    props = sorted(p for p in counts.object_properties(onto) | counts.data_properties(onto)
                   if art.is_owned(p))
    children = defaultdict(set)
    for s, o in onto.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            children[str(o)].add(str(s))
    hosts = set(ctx.profile.get("placeholder_hosts", ())) | set(art.config.get("placeholder_hosts") or ())

    matrix = {"classes": {c: {} for c in classes}, "properties": {p: {} for p in props}}
    used_values = Counter()
    for name in sorted(art.data_sets):
        g = art.data_graph(name)
        legacy = art.data_sets[name]["legacy"]
        files = [f.path for f in art.data_files(name)]
        typed = Counter(str(o) for o in g.objects(None, RDF.type))
        preds = Counter(str(p) for p in g.predicates())
        for c in classes:
            matrix["classes"][c][name] = typed.get(c, 0)
        for p in props:
            matrix["properties"][p][name] = preds.get(p, 0)
        for o in g.objects():
            if isinstance(o, URIRef):
                used_values[o] += 1
                for v in variants(o):
                    used_values[v] += 1

        collapsed = [c for c in classes if typed.get(c) and children.get(c)
                     and not any(typed.get(k) for k in children[c])]
        for c in collapsed:
            ctx.add("R8", errors.W_SUBCLASS_COLLAPSE, "minor",
                    f"{name}: uses {qname(tbox, c)} ({typed[c]}) but none of its "
                    f"{len(children[c])} subclasses",
                    "The data flattens the ontology's distinctions, so queries and shapes that "
                    "target the subclasses see nothing.", iri=c, files=files, count=typed[c],
                    evidence={"data_set": name, "subclasses": sorted(qname(tbox, k) for k in children[c])},
                    fix="Type the instances with the most specific class that applies.")

        _unused_allowed(ctx, art, tbox, g, name, files)
        _placeholders(ctx, g, name, files, legacy, hosts)
        _identity(ctx, tbox, g, name, files)
        _duplicates(ctx, g, name, files)
        _retyping(ctx, tbox, g, name, files)

    never = [c for c in classes if not any(matrix["classes"][c].values())] + \
        [p for p in props if not any(matrix["properties"][p].values())]
    if never:
        ctx.add("R8", errors.W_UNUSED_TERM, "info",
                f"{len(never)} declared classes and properties are never used in any data set",
                files=[f.path for f in art.by_role("ontology")], count=len(never),
                evidence={"terms": [qname(tbox, t) for t in never]})
    controlled = _controlled_values(art)
    unused_vals = sorted(v for v in controlled if not used_values.get(v))
    if unused_vals:
        ctx.add("R8", errors.W_UNUSED_TERM, "info",
                f"{len(unused_vals)} controlled-vocabulary values are never used in any data set",
                count=len(unused_vals),
                evidence={"values": [{"value": qname(tbox, v), "from": controlled[v]}
                                     for v in unused_vals[:60]]})
    per_set_unused = {name: [qname(tbox, p) for p in props if not matrix["properties"][p][name]]
                      for name in art.data_sets}
    ctx.add("R8", errors.I_FEATURE_USE, "info",
            "Feature use matrix: how each data set uses the ontology",
            "; ".join(f"{name}: {sum(1 for c in classes if matrix['classes'][c][name])} of "
                      f"{len(classes)} classes, {sum(1 for p in props if matrix['properties'][p][name])} "
                      f"of {len(props)} properties" for name in sorted(art.data_sets)),
            evidence={"classes": {qname(tbox, c): v for c, v in matrix["classes"].items()},
                      "properties": {qname(tbox, p): v for p, v in matrix["properties"].items()},
                      "unused_properties_by_data_set": per_set_unused})
    ctx.finish("R8", "Data profile",
               summary=f"{len(art.data_sets)} data sets profiled; "
                       f"{len(ctx.stage_findings('R8'))} observations.")


def _unused_allowed(ctx, art, tbox, g, name, files):
    """Values a shape allows (sh:in) that a data set never uses."""
    shapes = art.shapes_graph()
    allowed = defaultdict(set)
    for ps in shapes.subjects(SH["in"], None):
        p = shapes.value(ps, SH.path)
        if isinstance(p, URIRef):
            try:
                allowed[p] |= {x for x in Collection(shapes, shapes.value(ps, SH["in"]))
                               if isinstance(x, URIRef)}
            except Exception:  # noqa: BLE001
                pass
    rows = []
    for p, vals in sorted(allowed.items(), key=lambda x: str(x[0])):
        used = set(g.objects(None, p))
        if not used:
            continue   # a property the data set never uses is in the feature matrix
        missing = sorted(v for v in vals if v not in used)
        if missing:
            rows.append({"property": qname(tbox, p), "allowed": len(vals),
                         "never_used": [local(v) for v in missing]})
    if rows:
        ctx.add("R8", errors.W_UNUSED_TERM, "info",
                f"{name}: allowed values never used: " + "; ".join(
                    f"{r['property']} {', '.join(r['never_used'][:5])}" for r in rows[:3]),
                files=files, count=sum(len(r["never_used"]) for r in rows),
                evidence={"data_set": name, "by_property": rows})


def _placeholders(ctx, g, name, files, legacy, hosts):
    nodes = {x for t in g for x in (t[0], t[2]) if isinstance(x, URIRef)}
    subjects = {s for s in g.subjects() if isinstance(s, URIRef)}
    ph = {x for x in nodes if _host(x) in hosts or any(_host(x).endswith("." + h) for h in hosts)}
    if not ph:
        return
    share = len(ph & subjects) / len(subjects) if subjects else 0
    by_host = Counter(_host(x) for x in ph)
    ctx.add("R8", errors.W_PLACEHOLDER_IRI, "major" if share > 0.5 and not legacy else "minor",
            f"{name}: {len(ph):,} placeholder IRIs ({share:.0%} of subjects)",
            "Placeholder hosts such as example.org stand in for real identifiers; data that "
            "uses them cannot be linked or deduplicated.",
            files=files, count=len(ph),
            evidence={"data_set": name, "by_host": dict(by_host.most_common()),
                      "share_of_subjects": round(share, 3), "examples": sorted(map(str, ph))[:5]},
            fix="Mint real IRIs (or use the authority tables) for the entities the data refers to.")


def _identity(ctx, tbox, g, name, files):
    # agent-like properties that point at the entities themselves, not at
    # structured role nodes (whose IRIs repeat the role name by construction)
    props = {p for p in g.predicates() if AGENTISH.search(local(p))
             and not re.search(r"role|type|category", local(p), re.I)}
    values = set()
    for p in props:
        values.update(o for o in g.objects(None, p) if isinstance(o, (URIRef, Literal))
                      and len(set(g.predicates(o))) <= 2)
    if len(values) < 3:
        return
    clusters = defaultdict(set)
    compound = set()
    for v in values:
        text = local(v) if isinstance(v, URIRef) else str(v)
        label = g.value(v, RDFS.label) if isinstance(v, URIRef) else None
        for w in set(_words(text) + (_words(str(label)) if label else [])):
            clusters[w].add(v)
        if COMPOUND.search(text):
            compound.add(v)
    top = sorted(((w, vs) for w, vs in clusters.items() if len(vs) >= 3),
                 key=lambda x: -len(x[1]))[:10]
    if not top and not compound:
        return
    ctx.add("R8", errors.W_IDENTITY, "minor",
            f"{name}: {len(values)} distinct values name the agents"
            + (" (" + ", ".join(f"{len(vs)} contain '{w}'" for w, vs in top[:2]) + ")" if top else ""),
            "One real-world entity spread over several IRIs or spellings cannot be counted or "
            "queried as one.", files=files, count=sum(len(vs) for _, vs in top) + len(compound),
            evidence={"data_set": name, "properties": sorted(qname(tbox, p) for p in props),
                      "distinct_values": len(values),
                      "clusters": [{"token": w, "variants": len(vs),
                                    "examples": sorted(local(v) if isinstance(v, URIRef) else str(v)
                                                       for v in vs)[:5]} for w, vs in top],
                      "compound_values": len(compound),
                      "compound_examples": sorted(local(v) if isinstance(v, URIRef) else str(v)
                                                  for v in compound)[:5]},
            fix="Use one IRI per entity (an authority table where one exists) and split values "
                "that join several entities.")


def _duplicates(ctx, g, name, files):
    dupes, by_prop = 0, Counter()
    for s in set(g.subjects()):
        seen = Counter()
        for p, o in g.predicate_objects(s):
            if isinstance(o, BNode):
                seen[(p, _signature(g, o))] += 1
        for (p, _), n in seen.items():
            if n > 1:
                dupes += n - 1
                by_prop[p] += n - 1
    if dupes:
        top, n = by_prop.most_common(1)[0]
        ctx.add("R8", errors.W_DUPLICATE_NODE, "minor",
                f"{name}: {dupes} exact-duplicate blank nodes ({n} via {qname(g, top)})",
                "The same blank-node structure is attached to the same subject by the same "
                "property more than once.", files=files, count=dupes,
                evidence={"data_set": name, "by_property": {qname(g, p): n for p, n in by_prop.most_common(10)}},
                fix="Generate each structure once (or give it an IRI) when the data is built.")


def _retyping(ctx, tbox, g, name, files):
    domains = defaultdict(set)
    for p, c in tbox.subject_objects(RDFS.domain):
        if isinstance(c, URIRef):
            domains[p].add(c)
    sup = defaultdict(set)
    for s, o in tbox.subject_objects(RDFS.subClassOf):
        if isinstance(o, URIRef):
            sup[s].add(o)

    def closure(types):
        seen, todo = set(types), list(types)
        while todo:
            for parent in sup.get(todo.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    todo.append(parent)
        return seen

    asserted = defaultdict(set)
    for s, o in g.subject_objects(RDF.type):
        asserted[s].add(o)
    hits = Counter()
    cache = {}
    for s, p in {(s, p) for s, p, _ in g if p in domains}:
        if s not in cache:
            cache[s] = closure(asserted.get(s, set()))
        for c in domains[p]:
            if c not in cache[s]:
                hits[(c, p)] += 1
    if hits:
        ctx.add("R8", errors.W_DOMAIN_RETYPING, "info",
                f"{name}: {sum(hits.values()):,} subjects gain a class only through a property's domain",
                "A reasoner infers these memberships; the data never states them.",
                files=files, count=sum(hits.values()),
                evidence={"data_set": name,
                          "by_class_and_property": [{"class": qname(tbox, c), "property": qname(tbox, p),
                                                     "subjects": n} for (c, p), n in hits.most_common(15)]})
