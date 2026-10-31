"""R1 inventory, R2 OWL 2 profile (with the datatype patch), R2b design lint."""

import dataclasses
import os
import re
import subprocess
import tempfile

import rdflib
from rdflib import OWL, RDF, RDFS, XSD, BNode, Literal, URIRef
from rdflib.collection import Collection

from .. import counts, errors
from .artifact import is_standard, split_iri

# The OWL 2 datatype map (OWL 2 Structural Specification, section 4), plus
# rdfs:Literal and rdf:langString, which every OWL 2 reasoner accepts.
OWL2_DATATYPES = {XSD[x] for x in (
    "decimal integer nonNegativeInteger nonPositiveInteger positiveInteger negativeInteger "
    "long int short byte unsignedLong unsignedInt unsignedShort unsignedByte double float "
    "string normalizedString token language Name NCName NMTOKEN boolean hexBinary "
    "base64Binary anyURI dateTime dateTimeStamp").split()} | {
    RDFS.Literal, RDF.PlainLiteral, RDF.XMLLiteral, RDF.langString, OWL.real, OWL.rational}

CHARACTERISTICS = (OWL.FunctionalProperty, OWL.InverseFunctionalProperty, OWL.TransitiveProperty,
                   OWL.SymmetricProperty, OWL.AsymmetricProperty, OWL.ReflexiveProperty,
                   OWL.IrreflexiveProperty)
NEUTRAL_CLASSES = {OWL.Thing, RDFS.Resource, RDFS.Literal, RDF.langString,
                   rdflib.URIRef("http://www.w3.org/2004/02/skos/core#Concept"),
                   rdflib.URIRef("http://www.w3.org/2004/02/skos/core#ConceptScheme")}


_GENERATED_PREFIX = re.compile(r"^(default|ns)\d+:")


def qname(g, iri):
    """A prefixed name, or the namespace's last segment plus the local name when
    the graph has no prefix for it (rdflib would invent 'default3:')."""
    if g is None:
        return str(iri)
    try:
        name = g.namespace_manager.normalizeUri(URIRef(iri))
    except Exception:  # noqa: BLE001
        return str(iri)
    if _GENERATED_PREFIX.match(name) or name.startswith("<"):
        ns, ln = split_iri(iri)
        seg = ns.rstrip("#/").rsplit("/", 1)[-1]
        return f"{seg}{ns[-1] if ns else ''}{ln}" if ln else str(iri)
    return name


def local(iri):
    return split_iri(iri)[1] or str(iri)


# -- R1 --------------------------------------------------------------------------------

def run_r1(ctx):
    art = ctx.artifact
    rows = []
    totals = {"files": 0, "triples": 0, "classes": 0, "object_properties": 0,
              "data_properties": 0, "individuals": 0}
    for f in art.rdf_files():
        row = {"path": f.path, "role": f.role, "scope": f.scope, "triples": f.triples,
               "ontology_iri": f.ontology_iri, "version_iri": f.version_iri}
        if f.graph is not None:
            row.update(classes=len(counts.named_classes(f.graph)),
                       object_properties=len(counts.object_properties(f.graph)),
                       data_properties=len(counts.data_properties(f.graph)),
                       individuals=len(counts.named_individuals(f.graph)))
            for k in ("classes", "object_properties", "data_properties", "individuals"):
                totals[k] += row[k]
        rows.append(row)
        totals["files"] += 1
        totals["triples"] += f.triples
    tbox = art.tbox()
    c = counts.count(tbox) if len(tbox) else None
    ctx.finish("R1", "Parse and inventory", status="pass",
               summary=(f"{totals['files']} RDF files, {totals['triples']:,} triples; "
                        f"{len(art.by_role('ontology'))} ontology, {len(art.by_role('vocabulary'))} "
                        f"vocabularies, {len(art.by_role('shapes'))} shapes, "
                        f"{len(art.data_sets)} data sets"),
               notes={"files": rows, "totals": totals,
                      "tbox_counts": dataclasses.asdict(c) if c is not None else {}})


# -- R2 --------------------------------------------------------------------------------

def _members(g, node, seen=None):
    """Datatype IRIs a data range mentions (through unions, intersections, restrictions)."""
    seen = seen if seen is not None else set()
    if node in seen:
        return []
    seen.add(node)
    if isinstance(node, URIRef):
        out = [node]
        for eq in g.objects(node, OWL.equivalentClass):
            out += _members(g, eq, seen)
        return out
    out = []
    for p in (OWL.unionOf, OWL.intersectionOf, OWL.oneOf):
        for lst in g.objects(node, p):
            try:
                for x in Collection(g, lst):
                    out += _members(g, x, seen) if not isinstance(x, Literal) else []
            except Exception:  # noqa: BLE001 - malformed list
                pass
    for p in (OWL.onDatatype, OWL.datatypeComplementOf, OWL.equivalentClass):
        for x in g.objects(node, p):
            out += _members(g, x, seen)
    return out


def _is_datatype_iri(g, iri):
    return str(iri).startswith(str(XSD)) or (iri, RDF.type, RDFS.Datatype) in g \
        or iri in OWL2_DATATYPES


def _bad(g, iri):
    if iri in OWL2_DATATYPES:
        return False
    if str(iri).startswith(str(XSD)):
        return True
    if (iri, RDF.type, RDFS.Datatype) in g:
        # a custom datatype is fine only when it is defined in terms of the map
        defs = list(g.objects(iri, OWL.equivalentClass))
        return not defs or any(_bad(g, m) for d in defs for m in _members(g, d))
    return False


def _subtree(g, node):
    out, todo = set(), [node]
    while todo:
        n = todo.pop()
        if n in out or not isinstance(n, BNode):
            continue
        out.add(n)
        todo.extend(o for o in g.objects(n) if isinstance(o, BNode))
    return out


class DatatypePatch:
    """Rewrite a graph so standard OWL 2 reasoners can load it.

    Ranges and data ranges that use datatypes outside the map become
    rdfs:Literal, literals typed with them become plain strings, and imports
    are dropped (they never load from the network)."""

    def __init__(self, bad_props, bad_datatypes, range_nodes):
        self.bad_props = set(bad_props)
        self.bad_datatypes = set(bad_datatypes)
        self.range_nodes = set(range_nodes)   # (subject, predicate, object) to rewrite

    @property
    def empty(self):
        return not (self.bad_props or self.bad_datatypes)

    def apply(self, g):
        drop = set()
        for (_, _, o) in self.range_nodes:
            if isinstance(o, BNode):
                drop |= _subtree(g, o)
        out = rdflib.Graph()
        for prefix, ns in g.namespaces():
            out.bind(prefix, ns, override=False)
        for s, p, o in g:
            if p == OWL.imports or s in drop:
                continue
            if (s, p, o) in self.range_nodes:
                o = RDFS.Literal
            elif isinstance(o, Literal) and o.datatype is not None and o.datatype not in OWL2_DATATYPES:
                o = Literal(str(o))
            elif s in self.bad_datatypes and p == OWL.equivalentClass:
                continue
            out.add((s, p, o))
        return out


def find_datatype_problems(tbox, other_graphs):
    bad_props, bad_types, nodes, literal_counts = {}, set(), set(), {}
    for s, p, o in tbox.triples((None, None, None)):
        if p == RDFS.range or p in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.onDataRange,
                                    OWL.hasValue):
            if isinstance(o, Literal):
                continue
            mems = [m for m in _members(tbox, o) if _is_datatype_iri(tbox, m)]
            bad = [m for m in mems if _bad(tbox, m)]
            if not bad:
                continue
            nodes.add((s, p, o))
            for m in bad:
                if m in OWL2_DATATYPES:
                    continue
                if str(m).startswith(str(XSD)):
                    bad_types.add(m)
                else:
                    bad_types.add(m)
            prop = s if p == RDFS.range else tbox.value(s, OWL.onProperty)
            if prop is not None:
                bad_props.setdefault(prop, set()).update(bad)
    for name, g in [("tbox", tbox)] + list(other_graphs):
        for o in g.objects():
            if isinstance(o, Literal) and o.datatype is not None and o.datatype not in OWL2_DATATYPES:
                key = str(o.datatype)
                literal_counts.setdefault(key, {}).setdefault(name, 0)
                literal_counts[key][name] += 1
    expanded = set()
    for t in bad_types:
        expanded.add(t)
        for d in tbox.objects(t, OWL.equivalentClass):
            expanded.update(m for m in _members(tbox, d) if _bad(tbox, m))
    return bad_props, expanded, nodes, literal_counts


def _robot_profiles(tbox, budget=120):
    from kindwork.module_reasoner import _robot_cmd
    cmd = _robot_cmd()
    if not cmd:
        return None
    out = {}
    with tempfile.TemporaryDirectory(prefix="audit-profile-") as tmp:
        path = os.path.join(tmp, "tbox.owl")
        tbox.serialize(destination=path, format="xml")
        for prof in ("DL", "EL", "QL", "RL"):
            try:
                r = subprocess.run(cmd + ["validate-profile", "--profile", prof, "--input", path],
                                   capture_output=True, text=True, timeout=budget, check=False)
                out[prof] = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                out[prof] = None   # not decided within its share of the budget
    return out


def run_r2(ctx):
    art = ctx.artifact
    tbox = art.tbox()
    others = [(f.path, f.graph) for f in art.rdf_files()
              if f.graph is not None and f.role in ("data", "shapes")]
    bad_props, bad_types, nodes, literal_counts = find_datatype_problems(tbox, others)
    patch = DatatypePatch(bad_props, bad_types, nodes)
    patch.bad_datatypes |= {URIRef(k) for k in literal_counts}
    ctx.cache["patch"] = patch
    if bad_props or bad_types:
        names = sorted({qname(tbox, p) for p in bad_props}) + \
            sorted({qname(tbox, t) for t in bad_types})
        files = sorted({f.path for f in art.by_role("ontology") + art.by_role("vocabulary")
                        if any((p, RDFS.range, None) in f.graph for p in bad_props)})
        ctx.add("R2", errors.E_DATATYPE_PROFILE, "critical",
                f"Datatypes outside the OWL 2 datatype map: {', '.join(names)}",
                "Standard OWL 2 reasoners (HermiT, Pellet, the OWL API) refuse or misread "
                "these ranges, so the ontology cannot be reasoned over as released.",
                files=files, count=len(bad_props) + len(bad_types),
                evidence={"properties": {qname(tbox, p): sorted(qname(tbox, x) for x in v)
                                         for p, v in sorted(bad_props.items())},
                          "datatypes": sorted(qname(tbox, t) for t in bad_types),
                          "typed_literals": literal_counts},
                fix=("Use datatypes from the OWL 2 map (for example xsd:dateTime or xsd:string "
                     "with a pattern), or declare a custom datatype with owl:onDatatype and "
                     "facets over a map datatype."))
    if not patch.empty or literal_counts:
        ctx.patches.append({
            "name": "datatype patch",
            "detail": (f"{len(nodes)} ranges or data ranges became rdfs:Literal and literals of "
                       f"{len(literal_counts)} datatype(s) became plain strings; imports removed. "
                       "Every reasoning result is labeled 'with datatype patch'."),
            "properties": sorted(qname(tbox, p) for p in bad_props),
            "literal_datatypes": sorted(literal_counts),
        })
    prof = None
    if ctx.options.get("profiles", True) and len(tbox):
        try:
            prof = _robot_profiles(patch.apply(tbox), budget=ctx.budget.cap("reasoner"))
        except Exception as e:  # noqa: BLE001
            prof = {"error": str(e)[:200]}
    if prof is None:
        profile_note = "Profile membership not checked: ROBOT (Java) is not available."
    else:
        fits = [k for k, v in prof.items() if v is True]
        profile_note = f"TBox fits OWL 2 {', '.join(fits) or 'none of DL, EL, QL, RL'}."
        ctx.add("R2", errors.I_PROFILE, "info", profile_note, evidence={"profiles": prof})
    ctx.finish("R2", "OWL 2 profile",
               summary=("Datatypes outside the OWL 2 map; reasoning continues on a patched copy. "
                        if bad_props or bad_types else "All datatypes are in the OWL 2 map. ")
               + profile_note)


# -- R2b -------------------------------------------------------------------------------

INVERSE_PAIRS = (("before", "after"), ("starts", "startedby"), ("precedes", "follows"),
                 ("hasnext", "hasprevious"), ("parentof", "childof"), ("haspart", "partof"),
                 ("haspart", "ispartof"), ("ancestorof", "descendantof"), ("broader", "narrower"))
TRANSITIVE_NAMES = {"before", "after", "partof", "ispartof", "haspart", "iscomposedof",
                    "ancestorof", "descendantof", "precedes", "follows", "contains", "within"}


def _stem(word):
    w = word.lower()
    for suf in ("ies", "ed", "es", "s", "d", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _inverse_candidates(names):
    """Pairs of property IRIs whose names say they are inverses."""
    by_lower = {local(p).lower(): p for p in names}
    out = set()
    for a, b in INVERSE_PAIRS:
        if a in by_lower and b in by_lower:
            out.add((by_lower[a], by_lower[b]))
    for p in names:
        ln = local(p)
        m = re.match(r"^has([A-Z]\w*)$", ln)
        if m:
            for cand in (f"is{m.group(1)}Of", f"{m.group(1)[0].lower()}{m.group(1)[1:]}Of"):
                if cand.lower() in by_lower:
                    out.add((p, by_lower[cand.lower()]))
        m = re.match(r"^is([A-Z]\w*?)(By|Of)$", ln)
        if m:
            target = _stem(m.group(1))
            for q in names:
                if q != p and not local(q).startswith(("is", "has")) and _stem(local(q)) == target:
                    out.add((q, p))
    return out


def run_r2b(ctx):
    art = ctx.artifact
    onto = art.ontology_graph()
    tbox = art.tbox()
    if not len(onto):
        ctx.skip("R2b", "Design lint", "No ontology file in the artifact.")
        return
    ofiles = [f.path for f in art.by_role("ontology")]
    props = {p for p in counts.object_properties(onto) if art.is_owned(p)}
    props_all = props | {p for p in counts.data_properties(onto) if art.is_owned(p)}
    with_char = {s for t in CHARACTERISTICS for s in onto.subjects(RDF.type, t)}
    inverse_pairs = len({frozenset(t) for t in onto.subject_objects(OWL.inverseOf)})
    if props_all and not (with_char & {URIRef(p) for p in props_all}):
        ctx.add("R2b", errors.W_LINT_NO_CHARACTERISTICS, "minor",
                f"None of the {len(props_all)} properties declares any characteristic",
                "No property is functional, inverse-functional, transitive, symmetric, "
                "asymmetric, reflexive or irreflexive, so a reasoner can infer very little from "
                "the data and reject almost nothing"
                + (f" ({inverse_pairs} inverse pairs are declared)." if inverse_pairs else "."),
                files=ofiles, count=len(props_all), evidence={"inverse_pairs": inverse_pairs},
                fix="Declare the characteristics the documentation already implies "
                    "(for example functional for single-valued properties, inverses for paired ones).")

    inverses = {(str(a), str(b)) for a, b in onto.subject_objects(OWL.inverseOf)}
    missing = [(a, b) for a, b in sorted(_inverse_candidates(sorted(props)))
               if (a, b) not in inverses and (b, a) not in inverses]
    if missing:
        ctx.add("R2b", errors.W_LINT_INVERSE, "minor",
                f"{len(missing)} name-paired properties are not declared inverse",
                files=ofiles, count=len(missing),
                evidence={"pairs": [[qname(onto, a), qname(onto, b)] for a, b in missing]},
                fix="Add owl:inverseOf between each pair, or rename them if they are not inverses.")

    transitive = {str(s) for s in onto.subjects(RDF.type, OWL.TransitiveProperty)}
    chains = set()
    for f in art.data_files():
        for p in {p for p in f.graph.predicates() if str(p) in props and local(p).endswith("Of")}:
            for s, o in f.graph.subject_objects(p):
                if (o, p, None) in f.graph and o != s:
                    chains.add(str(p))
                    break
    likely = sorted(p for p in props if p not in transitive and
                    (local(p).lower() in TRANSITIVE_NAMES or p in chains))
    if likely:
        ctx.add("R2b", errors.W_LINT_TRANSITIVE, "minor",
                f"{len(likely)} likely-transitive properties are not declared transitive",
                files=ofiles, count=len(likely),
                evidence={"properties": [qname(onto, p) for p in likely],
                          "seen_in_chains_in_data": [qname(onto, p) for p in sorted(chains)]},
                fix="Declare them owl:TransitiveProperty if a chain a-b-c should imply a-c.")

    _lint_disjointness(ctx, art, onto, ofiles)
    _lint_foreign(ctx, art, onto, ofiles)
    _lint_oneof(ctx, tbox, onto, ofiles)
    ctx.finish("R2b", "Design lint",
               summary=f"{len(ctx.stage_findings('R2b'))} design suggestions.")


def _disjoint_pairs(g):
    pairs = {frozenset((str(a), str(b))) for a, b in g.subject_objects(OWL.disjointWith)}
    for node in list(g.subjects(RDF.type, OWL.AllDisjointClasses)):
        for lst in g.objects(node, OWL.members):
            items = [str(x) for x in Collection(g, lst)]
            pairs |= {frozenset((a, b)) for a in items for b in items if a != b}
    for _, lst in g.subject_objects(OWL.disjointUnionOf):
        items = [str(x) for x in Collection(g, lst)]
        pairs |= {frozenset((a, b)) for a in items for b in items if a != b}
    return pairs


def _lint_disjointness(ctx, art, onto, ofiles):
    classes = {c for c in counts.named_classes(onto) if art.is_owned(c)}
    pairs = _disjoint_pairs(onto)
    axioms = len(list(onto.subject_objects(OWL.disjointWith))) + \
        len(list(onto.subjects(RDF.type, OWL.AllDisjointClasses))) + \
        len(list(onto.subject_objects(OWL.disjointUnionOf)))
    by_local = {local(c): c for c in classes}
    typed = []
    for c in sorted(classes):
        for suffix in ("Type", "Category", "Kind"):
            other = by_local.get(local(c) + suffix)
            if other and frozenset((c, other)) not in pairs:
                typed.append([qname(onto, c), qname(onto, other)])
    children = {}
    for s, o in onto.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and str(s) in classes:
            children.setdefault(str(o), set()).add(str(s))
    open_parents = []
    for parent, kids in sorted(children.items()):
        kids = sorted(kids)
        if len(kids) >= 2 and not any(frozenset((a, b)) in pairs for a in kids for b in kids if a < b):
            open_parents.append({"parent": qname(onto, parent),
                                 "children": [qname(onto, k) for k in kids]})
    if typed or open_parents:
        ctx.add("R2b", errors.W_LINT_DISJOINT, "minor",
                f"Little disjointness: {axioms} disjointness axiom(s); "
                f"{len(open_parents)} parents whose subclasses are never disjoint",
                "Without disjointness a reasoner cannot reject an individual typed into two "
                "classes that should exclude each other.",
                files=ofiles, count=len(typed) + len(open_parents),
                evidence={"disjointness_axioms": axioms, "class_and_type_pairs": typed,
                          "sibling_groups": open_parents[:25]},
                fix="Declare sibling classes disjoint where an individual cannot be both "
                    "(owl:AllDisjointClasses), and keep X and XType disjoint.")


def _lint_foreign(ctx, art, onto, ofiles):
    hits = []
    for pred in (RDFS.domain, RDFS.range):
        for p, c in onto.subject_objects(pred):
            if not isinstance(c, URIRef) or c in NEUTRAL_CLASSES or str(c).startswith(str(XSD)):
                continue
            if (c, RDF.type, RDFS.Datatype) in onto:
                continue
            if not isinstance(p, URIRef) or art.is_owned(p):
                # Your own property with another vocabulary's class (a BFO
                # category, dcterms:Agent) is alignment, not a problem.
                continue
            if not art.is_owned(c) and split_iri(str(c))[0] == split_iri(str(p))[0]:
                # The other vocabulary's own axiom, shipped in an import extract.
                continue
            hits.append({"property": qname(onto, p), "axiom": local(pred),
                         "class": qname(onto, c),
                         "why": "a domain or range added to another vocabulary's property"})
    if hits:
        ctx.add("R2b", errors.W_LINT_FOREIGN_AXIOM, "minor",
                f"{len(hits)} domain or range axioms added to another vocabulary's properties",
                "A domain or range retypes every subject or object that uses the property, so "
                "one added to a property you do not own retypes other people's data too.",
                files=ofiles, count=len(hits), evidence={"axioms": hits[:40]},
                fix="Use a local subproperty, or a SHACL shape, instead of a domain or range "
                    "on a property you do not own.")


def _lint_oneof(ctx, tbox, onto, ofiles):
    distinct = set()
    for node in tbox.subjects(RDF.type, OWL.AllDifferent):
        for p in (OWL.distinctMembers, OWL.members):
            for lst in tbox.objects(node, p):
                distinct |= {str(x) for x in Collection(tbox, lst)}
    distinct |= {str(x) for t in tbox.subject_objects(OWL.differentFrom) for x in t}
    hits = []
    for r, filler in onto.subject_objects(OWL.allValuesFrom):
        for lst in onto.objects(filler, OWL.oneOf):
            items = [str(x) for x in Collection(onto, lst) if isinstance(x, URIRef)]
            if len(items) >= 2 and not all(i in distinct for i in items):
                hits.append({"property": qname(onto, onto.value(r, OWL.onProperty)),
                             "values": [qname(onto, i) for i in items][:12]})
    if hits:
        ctx.add("R2b", errors.W_LINT_ONEOF_UNA, "minor",
                f"{len(hits)} value lists (allValuesFrom over oneOf) without distinctness",
                "Under the open world a reasoner infers that a wrong value equals one of the "
                "listed values instead of reporting it.",
                files=ofiles, count=len(hits), evidence={"restrictions": hits},
                fix="Add owl:AllDifferent over the listed individuals, or check the values with SHACL sh:in.")
