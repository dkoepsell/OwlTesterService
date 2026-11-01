"""Guided remedies, plus the data-completion and version choices (spec 3.4).

Guided cards explain the problem and offer a template or table; nothing is
applied until the user writes or accepts the content.
"""

import re

import rdflib
from rdflib import OWL, RDF, RDFS, Literal, URIRef

from .catalog import MAX_ROWS, builder, letters, remedy
from .model import Remedy, RemedyOption
from .ops import n3

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")


@builder("E_SHACL")
def shacl(ctx, f):
    """Complete the data (a table of missing values), correct the shape, or declare."""
    import shacl_tools
    ev = f.get("evidence") or {}
    shapes = ctx.art.shapes_graph()
    rows, relax = [], {}
    for path in (f.get("files") or [])[:10]:
        af = ctx.art.get(path)
        if af is None or af.graph is None or not ctx.writable(path):
            continue
        try:
            res = shacl_tools.validate(af.graph, shapes, ont_graph=ctx.tbox, inference="rdfs")["results"]
        except Exception:  # noqa: BLE001 - shown in the explanation instead
            continue
        for x in res:
            if x.get("severity") != "Violation" or not x.get("path"):
                continue
            if x.get("constraint") == "MinCount" and len(rows) < MAX_ROWS:
                rows.append({"subject": x["focus_node"], "property": x["path"], "file": path,
                             "label": f"{x.get('focus_label') or x['focus_node']}: {x.get('path_label') or x['path']}",
                             "value": ""})
            if x.get("constraint") == "MinCount":
                relax.setdefault(x["path"], 0)
                relax[x["path"]] += 1
    opts, it = [], letters()
    if rows:
        opts.append(RemedyOption(
            id=next(it), recommended=True, label="Complete the data: give each missing value",
            consequence=("Each value you enter is added to its file. Rows left blank stay missing "
                         "and keep failing; enter an IRI in angle brackets or a quoted literal."),
            input={"kind": "table", "column": "value", "rows": rows},
            ops=[{"op": "add_triples", "args": {"table": True}}]))
    shape_ops = []
    for sf in ctx.rdf(("shapes",)):
        if not ctx.writable(sf.path):
            continue
        g = ctx.canonical(sf.path)
        for p in sorted(relax):
            for ps in g.subjects(SH.path, URIRef(p)):
                old = g.value(ps, SH.minCount)
                if old is not None and int(old) > 0:
                    shape_ops += [
                        {"op": "remove_triples", "args": {"file": sf.path, "triples": [[n3(ps), n3(SH.minCount), n3(old)]]}},
                        {"op": "add_triples", "args": {"file": sf.path, "triples": [[n3(ps), n3(SH.minCount), n3(Literal(0))]]}}]
    if shape_ops:
        opts.append(RemedyOption(
            id=next(it), label="Correct the shape: the values are optional",
            consequence=("sh:minCount drops to 0 for " + ", ".join(ctx.short(p) for p in sorted(relax)) +
                         ". Choose this only if the shape was wrong; data may then leave these out "
                         "everywhere, not only in this release."),
            ops=shape_ops))
    groups = ev.get("groups") or []
    explanation = "Most common violations:\n" + "\n".join(
        f"- {g.get('shape')} {g.get('path')} {g.get('constraint')} ({g.get('count')})" for g in groups[:10])
    return remedy(f, "choice" if opts else "guided", "Make the data pass its own shapes",
                  "A release whose data fails the shapes shipped with it tells users the shapes "
                  "cannot be trusted.", opts, explanation=explanation)


@builder("E_SELF_EXAMPLE")
def self_example(ctx, f):
    ev = f.get("evidence") or {}
    subject = URIRef(f.get("iri") or "")
    text = ev.get("example")
    if not text or not str(subject):
        return remedy(f, "guided", "Complete the documentation's examples",
                      f.get("message", ""), [], explanation=f.get("fix", ""))
    pred = None
    for p, o in ctx.tbox.predicate_objects(subject):
        if isinstance(o, Literal) and str(o).startswith(text[:200]):
            pred, old = p, o
            break
    path = ctx.declaring_file(subject, pred, old) if pred is not None else None
    if path is None or not ctx.writable(path):
        return None
    missing = "\n".join(f"- {v.get('focus_label')}: {v.get('path_label')} {v.get('constraint')}"
                        for v in ev.get("violations", []))
    opt = RemedyOption(
        id="a", recommended=True, label="Correct the example",
        consequence="The example in the documentation is replaced by your text, which is checked "
                    "against the shapes before it can be accepted.",
        input={"kind": "example", "label": "Example (Turtle)", "default": str(old),
               "lang": old.language or "", "validate": "shapes"},
        ops=[{"op": "remove_triples", "args": {"file": path, "triples": [[n3(subject), n3(pred), n3(old)]]}},
             {"op": "add_triples", "args": {"file": path, "triples": [[n3(subject), n3(pred), "{{literal}}"]]}}])
    return remedy(f, "guided", f"Correct the example for {ctx.short(subject)}",
                  "The documentation teaches users to write data the release itself rejects.", [opt],
                  explanation="What the shapes reject:\n" + missing)


@builder("E_PARSE")
def parse_error(ctx, f):
    return remedy(f, "guided", "Fix the syntax error by hand",
                  "The file could not be read, so the audit skipped it. Repair never rewrites a "
                  "file it cannot parse.", [],
                  explanation=f"{', '.join(f.get('files') or [])}\n\n{f.get('message', '')}")


@builder("W_IDENTITY")
def identity(ctx, f):
    ev = f.get("evidence") or {}
    ds = ev.get("data_set")
    props = [ctx.expand(p) for p in ev.get("properties") or []]
    props = [p for p in props if p is not None]
    files = [x for x in ctx.rdf(("data",)) if (ds is None or x.data_set == ds) and ctx.writable(x.path)]
    values = {}
    for x in files:
        for p in props:
            for o in x.graph.objects(None, p):
                if isinstance(o, URIRef):
                    values[str(o)] = values.get(str(o), 0) + 1
    rows = [{"subject": v, "label": f"{v} ({n} uses)", "target": ""}
            for v, n in sorted(values.items(), key=lambda x: (-x[1], x[0]))[:MAX_ROWS]]
    if not rows:
        return None
    opt = RemedyOption(
        id="a", recommended=True, label="Reconcile the variants: map each to one entity",
        consequence=("Each row you map is rewritten to the IRI you give (an authority table IRI "
                     "where one exists); rows left blank are unchanged."),
        input={"kind": "table", "column": "target", "rows": rows},
        ops=[{"op": "merge_nodes", "args": {"mode": "iris", "files": sorted(x.path for x in files),
                                            "table": True}}])
    return remedy(f, "guided", "Use one IRI per entity",
                  "One entity under several IRIs is counted, linked and queried as several.", [opt])


@builder("W_DOC_TERM")
def doc_term(ctx, f):
    ev = f.get("evidence") or {}
    terms = [URIRef(t) for t in ev.get("terms") or []]
    tok = ev.get("token")
    if tok and ":" in tok:
        x = ctx.expand(tok)
        if x is not None and ctx.art.is_owned(x):
            terms.append(x)
    target = next((x.path for x in ctx.rdf(("ontology",)) if ctx.writable(x.path)), None)
    if not terms or target is None:
        return remedy(f, "guided", "Correct the documentation", f.get("message", ""), [],
                      explanation=f"The text names {tok or 'a term'} that the ontology does not "
                                  "declare. Edit the annotation to name the right term.")
    draft = "".join(f"<{t}> a <{OWL.Class}> ;\n    <{RDFS.label}> \"{str(t).rsplit('#', 1)[-1].rsplit('/', 1)[-1]}\"@en .\n"
                    for t in terms)
    opt = RemedyOption(id="a", label=f"Declare the term(s) in {target}",
                       consequence="The terms the documentation names become part of the ontology. "
                                   "Correct the type and add definitions in the draft.",
                       ops=[{"op": "add_triples", "args": {"file": target, "turtle": "{{content}}"}}],
                       input={"kind": "turtle", "label": "Declarations", "default": draft})
    return remedy(f, "choice", "Declare what the documentation names", f.get("message", ""), [opt],
                  explanation="Or edit the note so it names the term that exists, and skip this card.")


@builder("W_VERSION")
def versions(ctx, f):
    found = sorted(((f.get("evidence") or {}).get("versions") or {}).keys())
    heads = []
    for x in ctx.rdf(("ontology",)):
        h = next((s for s in x.graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
        if h is not None and ctx.writable(x.path):
            heads.append((x.path, h, x.graph))
    if len(found) < 2 or not heads:
        return None
    opts, it = [], letters()
    for v in found[-3:][::-1]:
        ops = []
        for path, h, g in heads:
            for info in g.objects(h, OWL.versionInfo):
                if str(info) != v:
                    ops += [{"op": "remove_triples", "args": {"file": path, "triples": [[n3(h), n3(OWL.versionInfo), n3(info)]]}},
                            {"op": "add_triples", "args": {"file": path, "triples": [[n3(h), n3(OWL.versionInfo),
                                                                                      n3(Literal(v, datatype=info.datatype, lang=info.language))]]}}]
            for viri in g.objects(h, OWL.versionIRI):
                m = re.search(r"(?<![\w.])v?\d+\.\d+(?:\.\d+)?(?:[-.]?(?:rc|alpha|beta)\d*)?(?![\w.])", str(viri))
                if m and m.group(0).lstrip("v") != v:
                    new = str(viri)[:m.start()] + (m.group(0)[0] if m.group(0)[0] == "v" else "") + v + str(viri)[m.end():]
                    ops.append({"op": "rewrite_iri", "args": {"from": str(viri), "to": new, "mode": "iri",
                                                              "files": [path]}})
        if ops:
            opts.append(RemedyOption(
                id=next(it), recommended=not opts, label=f"Make every ontology header say {v}",
                consequence="owl:versionInfo and owl:versionIRI agree in every ontology file. "
                            "Version numbers in README, CHANGELOG or CI files are listed in the "
                            "finding; edit those by hand.", ops=ops))
    if not opts:
        return None
    return remedy(f, "choice", "Use one version number", "Disagreeing version numbers make it "
                  "unclear which release a user has.", opts)


def lens_gaps(ctx, lenses):
    """One guided remedy per lens with rows that found no candidate term."""
    out = []
    ns = (ctx.owned_namespaces() or ["https://example.invalid/ontology#"])[0]
    for t in lenses or []:
        gaps = [r for r in t.get("rows", []) if r.get("status") in ("no candidates", "rejected")]
        if not gaps:
            continue
        stubs = []
        for r in gaps:
            name = re.sub(r"[^A-Za-z0-9]", "", (r.get("node") or r["id"]).title())
            stubs.append(f"# {r.get('question', '')}\n<{ns}{name}> a <{OWL.Class}> ;\n"
                         f"    <{RDFS.label}> \"{r.get('node', name)}\"@en ;\n"
                         f"    <{RDFS.comment}> \"Define {r.get('node', name).lower()} for this domain.\"@en .\n")
        path = f"extensions/{t['lens']}-gaps.ttl"
        opt = RemedyOption(id="a", label=f"Start a module for the gaps ({path})",
                           consequence="A new module file declares a class for each gap. It is a "
                                       "starting point: align each class to the pattern before "
                                       "you publish it.",
                           ops=[{"op": "add_triples", "args": {"file": path, "turtle": "{{content}}"}}],
                           input={"kind": "turtle", "label": "Module", "default": "\n".join(stubs)})
        out.append(Remedy(id=f"M-lens-{t['lens']}", finding_id=f"lens:{t['lens']}", code="LENS_GAP",
                          kind="guided", title=f"{t.get('title', t['lens'])}: {len(gaps)} gap(s)",
                          rationale="The lens found no term for these parts of the pattern.",
                          options=[opt], severity="info",
                          explanation="\n".join(f"- {r.get('node')}: {r.get('question')}" for r in gaps)))
    return out
