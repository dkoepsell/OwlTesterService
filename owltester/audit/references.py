"""R5: reference integrity.

Every IRI in an owned namespace that the artifact uses (as a predicate, a type or
an object) must be declared by the ontology or a vocabulary. Dangling IRIs are
first tried against the variants that commonly break releases ('#' and '/'
swapped, a trailing slash, http and https, an old base replaced by the current
one); a declared variant makes the whole namespace pair one E_NS_MISMATCH.
"""

import re
from collections import Counter, defaultdict

from rdflib import OWL, RDF, RDFS, XSD, Literal, URIRef

from .. import errors
from .artifact import is_standard, split_iri
from .schema_checks import NEUTRAL_CLASSES, qname

SKIP_PREDICATES = {OWL.imports, OWL.versionIRI, OWL.priorVersion, RDFS.seeAlso, RDFS.isDefinedBy}


def declared_terms(art):
    out = set()
    for f in art.by_role("ontology") + art.by_role("vocabulary"):
        out.update(s for s in f.graph.subjects(RDF.type, None) if isinstance(s, URIRef))
        for iri in (f.ontology_iri, f.version_iri):
            if iri:
                out.add(URIRef(iri))
    return out


def _scheme_swap(ns):
    if ns.startswith("https://"):
        return "http://" + ns[8:]
    if ns.startswith("http://"):
        return "https://" + ns[7:]
    return ns


def _renames(art):
    """(old base, new base) pairs from owl:priorVersion and CHANGELOG namespace notes."""
    pairs = set()
    for f in art.by_role("ontology") + art.by_role("vocabulary"):
        for prior in f.graph.objects(None, OWL.priorVersion):
            if f.ontology_iri and str(prior).rstrip("#/") != f.ontology_iri.rstrip("#/"):
                pairs.add((str(prior).rstrip("#/"), f.ontology_iri.rstrip("#/")))
    for f in art.text_files():
        if not f.path.rsplit("/", 1)[-1].lower().startswith(("changelog", "history", "news")):
            continue
        for line in f.text().splitlines():
            if "namespace" not in line.lower():
                continue
            iris = re.findall(r"https?://[^\s`'\"<>)\]]+", line)
            if len(iris) >= 2:
                pairs.add((iris[0].rstrip("#/.,;"), iris[1].rstrip("#/.,;")))
    return pairs


def variants(iri, renames=()):
    ns, local = split_iri(iri)
    if not local:
        return []
    base = ns.rstrip("#/")
    spaces = {base + "#", base + "/", base + "/#"}
    for old, new in renames:
        if base == old or base.startswith(old + "/"):
            nb = new + base[len(old):]
            spaces |= {nb + "#", nb + "/"}
    spaces |= {_scheme_swap(s) for s in spaces}
    spaces.discard(ns)
    return [URIRef(s + local) for s in sorted(spaces)]


def _usages(art):
    """IRI -> Counter(file) for every predicate, type and object use."""
    used = defaultdict(Counter)
    for f in art.rdf_files():
        if f.graph is None or f.scope != "primary" or f.role == "other":
            continue
        for s, p, o in f.graph:
            if p in SKIP_PREDICATES:
                continue
            if isinstance(p, URIRef):
                used[p][f.path] += 1
            if isinstance(o, URIRef):
                used[o][f.path] += 1
    return used


def run_r5(ctx):
    art = ctx.artifact
    declared = declared_terms(art)
    if not declared:
        ctx.skip("R5", "Reference integrity", "No ontology or vocabulary declares any term.")
        return
    tbox = art.tbox()
    used = _usages(art)
    renames = _renames(art)
    dangling = {iri: files for iri, files in used.items()
                if art.is_owned(iri) and iri not in declared}
    pairs = defaultdict(lambda: {"iris": {}, "files": Counter()})
    undeclared = {}
    for iri, files in dangling.items():
        hit = next((v for v in variants(iri, renames) if v in declared), None)
        if hit is not None:
            key = (split_iri(iri)[0], split_iri(hit)[0])
            pairs[key]["iris"][str(iri)] = sum(files.values())
            pairs[key]["files"].update(files)
        else:
            undeclared[iri] = files

    owner = ctx.cache.setdefault("dangling_owner", {})
    for (wrong, right), info in sorted(pairs.items()):
        refs = sum(info["iris"].values())
        right_files = sorted({p for iri, files in used.items() if str(iri).startswith(right)
                              and iri in declared for p in files}
                             - {f.path for f in art.by_role("vocabulary") + art.by_role("ontology")})
        data_wrong = sorted(info["files"])
        f = ctx.add("R5", errors.E_NS_MISMATCH, "critical",
                    f"References use {wrong} but the vocabulary declares {right}",
                    f"{refs:,} references to {len(info['iris'])} terms in {len(data_wrong)} files "
                    f"point at '{wrong}', which declares nothing; the same terms exist under "
                    f"'{right}'. Every one of them is a dangling reference.",
                    files=data_wrong, count=refs,
                    evidence={"wrong_namespace": wrong, "declared_namespace": right,
                              "files_with_wrong_form": len(data_wrong),
                              "files_with_declared_form": len(right_files),
                              "references_by_term": dict(sorted(info["iris"].items(),
                                                                key=lambda x: -x[1])[:20])},
                    fix=f"Replace '{wrong}' with '{right}' in {len(data_wrong)} files.",
                    suggested_rewrite=f"{wrong} -> {right}")
        for iri in info["iris"]:
            owner[iri] = f.id

    for iri, files in sorted(undeclared.items(), key=lambda x: -sum(x[1].values())):
        f = ctx.add("R5", errors.E_UNDECLARED_TERM, "major",
                    f"Undeclared term {qname(tbox, iri)} ({sum(files.values())} uses in "
                    f"{len(files)} files)",
                    f"{iri} is in an owned namespace but no ontology or vocabulary file "
                    "declares it.", iri=str(iri), files=list(files), count=sum(files.values()),
                    evidence={"uses_by_file": dict(files.most_common(10))},
                    fix="Declare the term, or replace it with the declared term it stands for.")
        owner[str(iri)] = f.id
    ctx.cache["undeclared"] = {str(i) for i in undeclared}

    range_summary = _ranges(ctx, art, tbox, set(map(str, dangling)))
    minted = {s for f in art.rdf_files() if f.graph is not None for s in f.graph.subjects()}
    ext = Counter()
    for iri, files in used.items():
        if not art.is_owned(iri) and not is_standard(iri) and iri not in minted:
            ext[split_iri(iri)[0]] += sum(files.values())
    if ext:
        ctx.add("R5", errors.I_EXTERNAL_REFS, "info",
                f"{sum(ext.values()):,} references to {len(ext)} external namespaces (not checked)",
                count=sum(ext.values()), evidence={"by_namespace": dict(ext.most_common(15))})
    ctx.finish("R5", "Reference integrity",
               summary=(f"{len(declared):,} declared terms; {len(pairs)} namespace mismatches "
                        f"({sum(sum(i['iris'].values()) for i in pairs.values()):,} references); "
                        f"{len(undeclared)} undeclared terms. " + range_summary),
               notes={"declared_terms": len(declared), "dangling_terms": len(dangling),
                      "renames_considered": sorted(map(list, renames))})


def _closure(tbox, graph):
    sup = defaultdict(set)
    for s, o in tbox.subject_objects(RDFS.subClassOf):
        if isinstance(o, URIRef):
            sup[s].add(o)

    def up(c, seen=None):
        seen = seen if seen is not None else set()
        for p in sup.get(c, ()):
            if p not in seen:
                seen.add(p)
                up(p, seen)
        return seen

    types = defaultdict(set)
    for g in (tbox, graph):
        for s, o in g.subject_objects(RDF.type):
            types[s].add(o)
    return types, up


def _literal_problem(rng, lit):
    if rng == XSD.string and lit.language:
        return "language-tagged value on an xsd:string property"
    if rng == RDF.langString and not lit.language:
        return "untagged value on an rdf:langString property"
    if str(rng).startswith(str(XSD)) and rng != XSD.string and lit.datatype != rng:
        return f"value is not an xsd:{rng.split('#')[-1]}"
    return None


def _ranges(ctx, art, tbox, dangling):
    ranges = {p: o for p, o in tbox.subject_objects(RDFS.range)
              if isinstance(o, URIRef) and art.is_owned(p)}
    datatype_props = set(tbox.subjects(RDF.type, OWL.DatatypeProperty))
    per_prop = defaultdict(lambda: {"literal": Counter(), "class": 0, "untyped": set(),
                                    "examples": [], "files": set(), "by_set": Counter()})
    untagged_by_set = Counter()
    for name in sorted(art.data_sets):
        graph = art.data_graph(name)
        types, up = _closure(tbox, graph)
        for f in art.data_files(name):
            for s, p, o in f.graph:
                rng = ranges.get(p)
                if rng is None:
                    continue
                rec = per_prop[p]
                if isinstance(o, Literal):
                    prob = _literal_problem(rng, o)
                    if prob:
                        rec["literal"][prob] += 1
                        rec["by_set"][name] += 1
                        rec["files"].add(f.path)
                        if rng == RDF.langString:
                            untagged_by_set[name] += 1
                        if len(rec["examples"]) < 3:
                            rec["examples"].append(f"{qname(f.graph, s)} {qname(f.graph, p)} {o.n3()}")
                    continue
                if p in datatype_props or rng in NEUTRAL_CLASSES or not isinstance(o, URIRef) \
                        or str(o) in dangling:
                    continue
                ts = types.get(o, set())
                if not ts:
                    if (o, name) not in rec["untyped"]:
                        rec["untyped"].add((o, name))
                        rec["by_set"][name] += 1
                    rec["files"].add(f.path)
                    continue
                closed = set(ts)
                for t in ts:
                    closed |= up(t)
                if rng not in closed:
                    rec["class"] += 1
                    rec["by_set"][name] += 1
                    rec["files"].add(f.path)
                    if len(rec["examples"]) < 3:
                        rec["examples"].append(f"{qname(f.graph, o)} is never typed {qname(tbox, rng)}")
    for p, rec in sorted(per_prop.items(), key=lambda x: str(x[0])):
        lit = sum(rec["literal"].values())
        if not (lit or rec["class"] or rec["untyped"]):
            continue
        parts = [f"{n} {what}" for what, n in rec["literal"].items()]
        if rec["class"]:
            parts.append(f"{rec['class']} objects never typed with the range {qname(tbox, ranges[p])}")
        if rec["untyped"]:
            parts.append(f"{len(rec['untyped'])} objects are untyped")
        split = (" (" + ", ".join(f"{n} in {ds}" for ds, n in rec["by_set"].most_common()) + ")"
                 if len(rec["by_set"]) > 1 else f" in {next(iter(rec['by_set']))}")
        ctx.add("R5", errors.W_RANGE, "minor",
                f"{qname(tbox, p)}: " + "; ".join(parts) + split,
                "Under RDFS an untyped or mistyped object is silently retyped by the range, "
                "so these values are accepted without complaint." if rec["untyped"] or rec["class"]
                else "The values do not match the declared range.",
                iri=str(p), files=rec["files"], count=lit + rec["class"] + len(rec["untyped"]),
                evidence={"range": qname(tbox, ranges[p]), "literal_problems": dict(rec["literal"]),
                          "class_mismatches": rec["class"], "untyped_objects": len(rec["untyped"]),
                          "by_data_set": dict(rec["by_set"]), "examples": rec["examples"]},
                fix="Type the objects with the range class, or fix the literal's tag or datatype.")
    ctx.cache["untagged_langstrings"] = dict(untagged_by_set)
    if not untagged_by_set:
        return ""
    return ("Untagged strings on rdf:langString properties: "
            + ", ".join(f"{n} in {ds}" for ds, n in untagged_by_set.most_common()) + ".")
