"""R3: reasoning over the TBox, each data set and each inconsistent file.

Every call goes through ``kindwork.module_reasoner.consistency`` (HermiT with a
Pellet cross-check, offline). Inputs are the datatype-patched copies from R2.
For an inconsistent file, a minimal inconsistent set of its triples is found by
delta debugging with the TBox held fixed; when the budget runs out the smallest
set found so far is reported and labeled as possibly not minimal.
"""

import contextlib
import io
import os
import tempfile
import time

import rdflib
from rdflib import OWL, RDF, RDFS, XSD, Literal, URIRef
from rdflib.collection import Collection

from .. import errors
from .context import TimedOut, run_with_timeout
from .schema_checks import _disjoint_pairs, qname

LABEL = "with datatype patch"


PELLET_NOTE = ("Pellet 2.3 predates rdf:langString, so its cross-check reads rdf:langString "
               "ranges as rdf:PlainLiteral.")


def _write_nt(graph):
    fd, path = tempfile.mkstemp(suffix=".nt", prefix="audit-")
    os.close(fd)
    graph.serialize(destination=path, format="nt", encoding="utf-8")
    return path


def _check(ctx, graph, cross_check=False, budget=None):
    from kindwork.module_reasoner import consistency
    budget = budget or ctx.budget.cap("reasoner")
    paths = [_write_nt(graph)]
    try:
        pellet_path = None
        if cross_check and (None, RDFS.range, RDF.langString) in graph:
            variant = rdflib.Graph()
            for s, p, o in graph:
                variant.add((s, p, RDF.PlainLiteral if p == RDFS.range and o == RDF.langString else o))
            pellet_path = _write_nt(variant)
            paths.append(pellet_path)
            ctx.cache["pellet_note"] = PELLET_NOTE
        return consistency(paths[0], budget, with_bfo=ctx.profile.get("reason_with_bfo", False),
                           cross_check=cross_check, pellet_path=pellet_path)
    finally:
        for p in paths:
            os.remove(p)


def _patched(ctx, graph):
    patch = ctx.cache.get("patch")
    return patch.apply(graph) if patch is not None else graph


def _union(*graphs):
    out = rdflib.Graph()
    for g in graphs:
        for prefix, ns in g.namespaces():
            out.bind(prefix, ns, override=False)
        for t in g:
            out.add(t)
    return out


def _legacy(ctx, data_set):
    return ctx.artifact.data_sets.get(data_set, {}).get("legacy", False)


def _note_disagreement(ctx, res, what, files=()):
    if res.get("disagreement"):
        ctx.add("R3", errors.E_REASONER_DISAGREE, "major",
                f"HermiT and Pellet disagree on {what}",
                res["disagreement"] + " This is a tool finding: neither verdict can be trusted "
                "until it is understood.", files=files)


def _inferred_subsumptions(ctx, tbox):
    """Stage C's non-triviality count, reported as information."""
    from ..context import GateContext
    from ..stages import stage_c
    fd, path = tempfile.mkstemp(suffix=".ttl", prefix="audit-tbox-")
    os.close(fd)
    try:
        tbox.serialize(destination=path, format="turtle")
        gctx = GateContext(path, kernel=None)
        # owlready2 echoes the Java command line for Pellet
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r = run_with_timeout(stage_c.run, ctx.budget.cap("reasoner"), gctx)
        return r.notes.get("inferred_subsumptions"), r.notes.get("inferred_examples", [])
    except (TimedOut, Exception):  # noqa: BLE001 - informational only
        return None, []
    finally:
        os.remove(path)


def run_r3(ctx):
    art = ctx.artifact
    raw_tbox = art.tbox()
    if not len(raw_tbox):
        ctx.skip("R3", "Reasoning", "No ontology or vocabulary to reason over.")
        return
    tbox = _patched(ctx, raw_tbox)
    ctx.cache["patched_tbox"] = tbox
    ctx.progress("R3", "TBox")
    tfiles = [f.path for f in art.by_role("ontology") + art.by_role("vocabulary")]
    res = _check(ctx, tbox, cross_check=True)
    notes = {"label": LABEL if ctx.patches else "", "tbox": res["status"], "data_sets": {},
             "files": {}}
    _note_disagreement(ctx, res, "the TBox", tfiles)
    if res["status"] in ("timeout", "error"):
        ctx.limit("R3", "reasoner", f"TBox: {res['detail']}")
        ctx.finish("R3", "Reasoning", status="skipped",
                   summary=f"The reasoner could not decide the TBox: {res['detail']}", notes=notes)
        return
    if res["status"] == "inconsistent":
        ctx.add("R3", errors.E_INCONSISTENT, "critical", "The ontology is inconsistent",
                f"HermiT finds the TBox inconsistent ({LABEL}); nothing can be inferred from it.",
                files=tfiles, fix="Find the clash with an explanation tool (robot explain) and remove it.")
        ctx.finish("R3", "Reasoning", summary="TBox inconsistent; data not reasoned over.", notes=notes)
        return
    for iri in sorted(res["unsatisfiable"]):
        ctx.add("R3", errors.E_UNSAT, "critical", f"Unsatisfiable class: {qname(tbox, iri)}",
                "No individual can ever belong to this class; any data typed with it is "
                "inconsistent.", iri=iri, files=tfiles)
    inferred, examples = _inferred_subsumptions(ctx, tbox)
    notes.update(unsatisfiable=len(res["unsatisfiable"]), inferred_subsumptions=inferred,
                 inferred_examples=examples)
    if inferred == 0:
        notes["non_triviality"] = ("The reasoner entailed no subsumption beyond what is "
                                   "asserted: the TBox is consistent, but says little a reasoner "
                                   "can use.")

    inconsistent_files = []
    for name in sorted(art.data_sets):
        if ctx.budget.expired():
            ctx.limit("R3", "total", f"data set {name} not reasoned over")
            continue
        ctx.progress("R3", f"data set {name}")
        files = art.data_files(name)
        r = _check(ctx, _union(tbox, _patched(ctx, art.data_graph(name))), cross_check=True)
        _note_disagreement(ctx, r, f"data set {name}", [f.path for f in files])
        notes["data_sets"][name] = r["status"]
        if r["status"] == "ok":
            continue
        if r["status"] in ("timeout", "error"):
            # the set as a whole could not be decided: fall back to file by file
            ctx.limit("R3", "reasoner", f"data set {name}: {r['detail']} Reasoned file by file instead.")
        for f in files:
            if ctx.budget.expired():
                ctx.limit("R3", "total", f"{f.path} not reasoned over")
                break
            fr = _check(ctx, _union(tbox, _patched(ctx, f.graph)))
            notes["files"][f.path] = fr["status"]
            if fr["status"] == "inconsistent":
                inconsistent_files.append(f)
            elif fr["status"] in ("timeout", "error"):
                ctx.limit("R3", "reasoner", f"{f.path}: {fr['detail']}")

    explained = 0
    by_set = {}
    for f in inconsistent_files:
        by_set.setdefault(f.data_set, []).append(f)
    for name, files in by_set.items():
        legacy = _legacy(ctx, name)
        total = len(art.data_files(name))
        for f in files:
            evidence, message = {}, ""
            if ctx.options.get("explain", True) and explained < ctx.budget["max_explanations"]:
                ctx.progress("R3", f"explaining {f.path}")
                explained += 1
                evidence = explain(ctx, tbox, f)
                message = " ".join(evidence.get("causes", []))
            ctx.add("R3", errors.E_ABOX_INCONSISTENT, "major" if legacy else "critical",
                    f"Data file contradicts the ontology: {f.path}",
                    message or "The file is inconsistent with the ontology and vocabularies "
                               f"({LABEL}).",
                    files=[f.path], evidence=dict(evidence, data_set=name,
                                                  inconsistent_in_set=f"{len(files)} of {total}"),
                    fix=evidence.get("fix", "Correct the triples listed as the minimal cause."))
    if len(inconsistent_files) > explained and ctx.options.get("explain", True):
        ctx.limit("R3", "max_explanations",
                  f"{len(inconsistent_files) - explained} inconsistent files were not explained")
    if ctx.cache.get("pellet_note"):
        notes["pellet"] = ctx.cache["pellet_note"]
    summary = (f"TBox consistent, {len(res['unsatisfiable'])} unsatisfiable classes"
               + (f", {inferred} inferred subsumptions" if inferred is not None else "")
               + f"; {len(inconsistent_files)} inconsistent data files"
               + (f" ({LABEL})." if ctx.patches else "."))
    ctx.finish("R3", "Reasoning", summary=summary, notes=notes)


# -- explanation -------------------------------------------------------------------------

def _suspects(tbox, g):
    """Subjects whose triples are likely to hold the clash, to seed the search."""
    out = set()
    ranges = {p: o for p, o in tbox.subject_objects(RDFS.range)}
    for s, p, o in g:
        r = ranges.get(p)
        if isinstance(o, Literal) and r is not None:
            if (r == XSD.string and o.language) or (r == RDF.langString and not o.language) or \
                    (str(r).startswith(str(XSD)) and r != XSD.string and o.datatype != r):
                out.add(s)
    types = _types(tbox, g)
    pairs = _disjoint_pairs(tbox)
    for node, ts in types.items():
        names = {str(t) for t, _ in ts}
        if any(frozenset((a, b)) in pairs for a in names for b in names if a < b):
            out.add(node)
    return out


def _superclasses(tbox):
    sup = {}
    for s, o in tbox.subject_objects(RDFS.subClassOf):
        if isinstance(o, URIRef):
            sup.setdefault(s, set()).add(o)
    return sup


def _types(tbox, g):
    """node -> {(class, how)} from asserted types, domains and ranges, closed upward."""
    domains = {p: o for p, o in tbox.subject_objects(RDFS.domain) if isinstance(o, URIRef)}
    ranges = {p: o for p, o in tbox.subject_objects(RDFS.range) if isinstance(o, URIRef)}
    sup = _superclasses(tbox)
    out = {}
    for s, p, o in g:
        if p == RDF.type and isinstance(o, URIRef):
            out.setdefault(s, set()).add((o, "asserted"))
        if p in domains:
            out.setdefault(s, set()).add((domains[p], f"domain of {p}"))
        if p in ranges and not isinstance(o, Literal):
            out.setdefault(o, set()).add((ranges[p], f"range of {p}"))
    for node, ts in out.items():
        todo = list(ts)
        while todo:
            c, how = todo.pop()
            for parent in sup.get(c, ()):
                if (parent, how) not in ts:
                    ts.add((parent, how))
                    todo.append((parent, how))
    return out


def _minimize(ctx, tbox, triples, deadline):
    """Complement-only ddmin: always holds an inconsistent superset."""
    current, n, checks = list(triples), 2, 0
    while len(current) >= 2:
        if time.monotonic() > deadline:
            return current, False, checks
        chunk = max(1, -(-len(current) // n))
        reduced = False
        for i in range(0, len(current), chunk):
            if time.monotonic() > deadline:
                return current, False, checks
            cand = current[:i] + current[i + chunk:]
            g = rdflib.Graph()
            for t in cand:
                g.add(t)
            checks += 1
            r = _check(ctx, _union(tbox, g), budget=max(1, deadline - time.monotonic()))
            if r["status"] == "inconsistent":
                current, n, reduced = cand, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(current):
                return current, True, checks
            n = min(len(current), n * 2)
    return current, True, checks


def explain(ctx, tbox, f):
    budget = ctx.budget.cap("explain")
    deadline = time.monotonic() + budget
    g = _patched(ctx, f.graph)
    suspects = _suspects(_union(tbox, g), g)
    seed = [t for t in g if t[0] in suspects or t[2] in suspects]
    start = list(g)
    if seed and len(seed) < len(start):
        sg = rdflib.Graph()
        for t in seed:
            sg.add(t)
        if _check(ctx, _union(tbox, sg), budget=min(budget, ctx.budget["reasoner"]))["status"] == "inconsistent":
            start = seed
    triples, minimal, checks = _minimize(ctx, tbox, sorted(start), deadline)
    if not minimal:
        ctx.limit("R3", "explain", f"{f.path}: explanation budget ran out after {checks} checks")
    mg = rdflib.Graph()
    for prefix, ns in f.graph.namespaces():
        mg.bind(prefix, ns, override=False)
    for t in triples:
        mg.add(t)
    labels = {}
    for node in {x for t in triples for x in (t[0], t[1], t[2]) if isinstance(x, URIRef)}:
        lab = tbox.value(node, RDFS.label) or f.graph.value(node, RDFS.label)
        if lab is not None:
            labels[qname(mg, node)] = str(lab)
    causes = describe(_union(tbox, g), mg)
    return {"minimal_triples": mg.serialize(format="turtle"), "triple_count": len(triples),
            "minimal": minimal, "checks": checks, "labels": labels, "causes": causes,
            "note": "" if minimal else "The budget ran out; this set may not be minimal.",
            "fix": _fix_for(causes)}


def describe(tbox, mg):
    """Plain-language sentences for recognised patterns in a minimal set."""
    out = []
    ranges = {p: o for p, o in tbox.subject_objects(RDFS.range)}
    for s, p, o in mg:
        r = ranges.get(p)
        if not isinstance(o, Literal) or r is None:
            continue
        if r == XSD.string and o.language:
            out.append(f'The value "{o}"@{o.language} of {qname(mg, p)} is language-tagged, but '
                       f"{qname(mg, p)} has range xsd:string, which excludes language-tagged strings.")
        elif r == RDF.langString and not o.language:
            out.append(f'The value "{o}" of {qname(mg, p)} has no language tag, but '
                       f"{qname(mg, p)} has range rdf:langString.")
        elif str(r).startswith(str(XSD)) and r != XSD.string and o.datatype != r:
            out.append(f'The value "{o}" of {qname(mg, p)} is not a {qname(mg, r)}, '
                       f"which is the property's range.")
    pairs = _disjoint_pairs(tbox)
    for node, ts in _types(tbox, mg).items():
        items = sorted(ts, key=lambda x: (x[1] != "asserted", str(x[0])))
        for i, (a, how_a) in enumerate(items):
            for b, how_b in items[i + 1:]:
                if frozenset((str(a), str(b))) in pairs:
                    out.append(f"{qname(mg, node)} is a {qname(mg, a)} ({_how(mg, how_a)}) and a "
                               f"{qname(mg, b)} ({_how(mg, how_b)}), and {qname(mg, a)} and "
                               f"{qname(mg, b)} are declared disjoint.")
                    break
            else:
                continue
            break
    if not out:
        functional = {s for s in tbox.subjects(RDF.type, OWL.FunctionalProperty)}
        for p in {p for _, p, _ in mg}:
            if p in functional:
                out.append(f"{qname(mg, p)} is functional, but the set gives it more than one value.")
        for node, lst in tbox.subject_objects(OWL.oneOf):
            vals = set(Collection(tbox, lst))
            if any(o not in vals for _, _, o in mg if isinstance(o, URIRef) and (o, None, None) in tbox):
                out.append("A value lies outside an enumerated list (owl:oneOf) the ontology requires.")
                break
    return out or ["The triples above are inconsistent with the ontology together; no common "
                   "pattern (datatype clash, disjoint classes, cardinality) was recognised."]


def _how(mg, how):
    if how == "asserted":
        return "asserted"
    kind, _, prop = how.partition(" of ")
    return f"through the {kind.split()[0]} of {qname(mg, prop)}"


def _fix_for(causes):
    text = " ".join(causes)
    if "language-tagged" in text:
        return "Drop the language tag, or change the property's range to rdf:langString."
    if "no language tag" in text:
        return "Add a language tag, or change the property's range to xsd:string."
    if "declared disjoint" in text:
        return ("Type the individual correctly, or move the domain or range that adds the second "
                "class to a subproperty used only for that class.")
    return "Correct or remove the triples listed as the minimal cause."
