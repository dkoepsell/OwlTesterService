"""R7: documentation integrity and self-examples.

Annotation text is scanned for terms the ontology never declares, with token
rules kept conservative and listed in the report. Turtle snippets in usage
examples are parsed with the ontology's prefixes, checked for undeclared terms
and validated against the artifact's own shapes.
"""

import re
from collections import defaultdict

import rdflib
from rdflib import RDFS, Literal, URIRef
from rdflib.namespace import SKOS

from .. import errors
from .artifact import is_standard, parse_text_snippet, split_iri
from .references import declared_terms
from .schema_checks import qname

VANN_EXAMPLE = URIRef("http://purl.org/vocab/vann/usageExample")
DOC_PREDICATES = (RDFS.comment, SKOS.scopeNote, SKOS.definition, SKOS.note, SKOS.example,
                  SKOS.editorialNote, SKOS.historyNote, VANN_EXAMPLE,
                  URIRef("http://purl.org/dc/terms/description"))
EXAMPLE_PREDICATES = (VANN_EXAMPLE, SKOS.example, RDFS.comment)
TOKEN_RULES = {
    "curie": r"a prefixed name with one of the artifact's own prefixes (lomo:hasCondition)",
    "camel": r"a lowerCamelCase identifier with two or more humps (usesDefinition)",
    "paren": r"an UpperCamelCase word in parentheses ((TemporalRule))",
}
URL = re.compile(r"https?://\S+|<[^>]+>")
CAMEL = re.compile(r"(?<![\w:/#.-])([a-z]{2,}(?:[A-Z][a-z0-9]+)+)(?![\w:/-])")
PAREN = re.compile(r"\(([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\)")
TURTLE_HINT = re.compile(r"(\s(a|rdf:type)\s|\w:\w+\s+[\w<\"]).*\s\.\s*($|\n)", re.S)


def _prefixes(art):
    out = {}
    for f in art.by_role("ontology") + art.by_role("vocabulary") + art.by_role("shapes"):
        for p, ns in f.graph.namespaces():
            if p:
                out.setdefault(p, str(ns))
    out.setdefault("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    out.setdefault("rdfs", str(RDFS))
    out.setdefault("xsd", "http://www.w3.org/2001/XMLSchema#")
    out.setdefault("skos", str(SKOS))
    return out


def _known_locals(art, declared):
    owned = defaultdict(set)
    any_local = set()
    for t in declared:
        ns, ln = split_iri(t)
        owned[ns].add(ln)
        any_local.add(ln)
    for f in art.rdf_files():
        if f.graph is None:
            continue
        for t in f.graph:
            for x in t:
                if isinstance(x, URIRef) and is_standard(x):
                    any_local.add(split_iri(x)[1])
    return owned, any_local


PREFIX_USE = re.compile(r"(?<![\w<\"/#:.-])([A-Za-z][\w-]*):(?=[A-Za-z_])")


def _example_prefixes(text, prefixes):
    """The ontology's prefixes, plus a placeholder namespace for any prefix the
    example uses without binding (``ex:`` is the usual one)."""
    bare = re.sub(r'"[^"]*"|<[^>]*>|#[^\n]*', " ", text)
    extra = {p: f"http://example.org/{p}/" for p in PREFIX_USE.findall(bare)
             if p not in prefixes and p not in ("http", "https", "urn", "mailto")}
    declared = set(re.findall(r"@prefix\s+([\w-]*):", text, re.I))
    return [(p, ns) for p, ns in {**prefixes, **extra}.items() if p not in declared]


def _example_snippets(art, prefixes):
    out = []
    for f in art.by_role("ontology") + art.by_role("vocabulary"):
        for s, p, lit in f.graph:
            if p not in EXAMPLE_PREDICATES or not isinstance(lit, Literal):
                continue
            text = str(lit)
            if not TURTLE_HINT.search(text):
                continue
            # the file's own prefixes first (including its default ':'), then the rest
            local_prefixes = {p: str(ns) for p, ns in f.graph.namespaces()}
            g, err = parse_text_snippet(text, _example_prefixes(text, {**prefixes, **local_prefixes}))
            if g is not None and len(g):
                out.append({"subject": s, "predicate": p, "file": f.path, "graph": g, "text": text})
    return out


def run_r7(ctx):
    art = ctx.artifact
    docs_files = art.by_role("ontology") + art.by_role("vocabulary")
    if not docs_files:
        ctx.skip("R7", "Documentation integrity and self-examples", "No ontology or vocabulary.")
        return
    tbox = art.tbox()
    declared = declared_terms(art)
    prefixes = _prefixes(art)
    owned_prefixes = {p: ns for p, ns in prefixes.items() if art.is_owned(URIRef(ns + "x"))}
    owned_locals, any_local = _known_locals(art, declared)
    all_owned_locals = set().union(*owned_locals.values()) if owned_locals else set()

    examples = _example_snippets(art, prefixes)
    example_literals = {(e["subject"], e["predicate"], e["text"]) for e in examples}

    mentions = defaultdict(lambda: {"where": set(), "rule": "", "files": set()})
    for f in docs_files:
        for s, p, lit in f.graph:
            if p not in DOC_PREDICATES or not isinstance(lit, Literal) or \
                    (s, p, str(lit)) in example_literals:
                continue
            text = URL.sub(" ", str(lit))
            where = f"{p.n3(f.graph.namespace_manager)} of {qname(f.graph, s)}"
            for prefix, ns in owned_prefixes.items():
                for m in re.finditer(rf"(?<![\w-]){re.escape(prefix)}:([A-Za-z_][\w-]*)", text):
                    iri = URIRef(ns + m.group(1))
                    if iri not in declared:
                        rec = mentions[f"{prefix}:{m.group(1)}"]
                        rec["where"].add(where), rec["files"].add(f.path)
                        rec["rule"] = "curie"
            for rule, rx in (("camel", CAMEL), ("paren", PAREN)):
                for m in rx.finditer(text):
                    tok = m.group(1)
                    if tok in any_local or tok in all_owned_locals or tok in mentions:
                        continue
                    rec = mentions[tok]
                    rec["where"].add(where), rec["files"].add(f.path)
                    rec["rule"] = rule
    for tok, rec in sorted(mentions.items()):
        ctx.add("R7", errors.W_DOC_TERM, "minor",
                f"Documentation names {tok}, which is not declared",
                f"Found in {len(rec['where'])} annotation(s); matched by the '{rec['rule']}' rule.",
                files=rec["files"], count=len(rec["where"]),
                evidence={"token": tok, "rule": TOKEN_RULES[rec["rule"]],
                          "where": sorted(rec["where"])[:10]},
                fix="Declare the term, or correct the text to name the term that exists.")

    shapes = art.shapes_graph() if art.by_role("shapes") else None
    results = []
    if shapes is not None and examples:
        # one validation over all examples; violations are attributed by focus node
        import shacl_tools
        batch = rdflib.Graph()
        for e in examples:
            for t in e["graph"]:
                batch.add(t)
        try:
            results = [x for x in shacl_tools.validate(batch, shapes, ont_graph=tbox,
                                                       inference="rdfs")["results"]
                       if x["severity"] == "Violation"]
        except Exception as ex:  # noqa: BLE001
            ctx.limit("R7", "shacl", f"examples could not be validated: {str(ex)[:200]}")
    failing, fragments = 0, []
    sup = defaultdict(set)
    for s, o in tbox.subject_objects(RDFS.subClassOf):
        sup[o].add(s)

    def subclasses(c):
        seen, todo = {c}, [c]
        while todo:
            for k in sup.get(todo.pop(), ()):
                if k not in seen:
                    seen.add(k)
                    todo.append(k)
        return seen

    for e in examples:
        undeclared = sorted({str(x) for t in e["graph"] for x in (t[1], t[2])
                             if isinstance(x, URIRef) and art.is_owned(x) and x not in declared})
        if undeclared:
            ctx.add("R7", errors.W_DOC_TERM, "minor",
                    f"Example on {qname(tbox, e['subject'])} uses undeclared terms",
                    ", ".join(qname(tbox, u) for u in undeclared[:8]),
                    files=[e["file"]], count=len(undeclared),
                    evidence={"terms": undeclared, "rule": "terms inside a Turtle example"},
                    fix="Make the example use declared terms.")
        mine = {str(s) for s in e["graph"].subjects()}
        viol = [x for x in results if x["focus_node"] in mine]
        # An example on a class shows a whole instance of it; an example on a
        # property is usually a fragment that leaves out unrelated required fields.
        kinds = subclasses(e["subject"])
        instances = {str(s) for s, o in e["graph"].subject_objects(rdflib.RDF.type) if o in kinds}
        whole = [x for x in viol if x["focus_node"] in instances]
        if viol and not whole:
            fragments.append((e, viol))
            continue
        viol = whole
        if viol:
            failing += 1
            ctx.add("R7", errors.E_SELF_EXAMPLE, "major",
                    f"The ontology's own example for {qname(tbox, e['subject'])} fails its shapes",
                    "; ".join(dict.fromkeys(f"{x['focus_label']}: {x['path_label'] or ''} "
                                            f"{x['constraint']} ({x['message'][:120]})"
                                            for x in viol[:4])),
                    iri=str(e["subject"]), files=[e["file"]], count=len(viol),
                    evidence={"annotation": e["predicate"].n3(tbox.namespace_manager),
                              "violations": [{k: x[k] for k in ("focus_label", "path_label",
                                                                "constraint", "message")}
                                             for x in viol[:10]],
                              "example": e["text"][:3000]},
                    fix="Correct the example: the documentation teaches users to write data the "
                        "artifact itself rejects.")
    if fragments:
        ctx.add("R7", errors.E_SELF_EXAMPLE, "minor",
                f"{len(fragments)} example fragments would fail the shapes if used as data",
                "These examples illustrate one property and leave out fields the shapes require. "
                "Readers who copy them get invalid data.",
                files=sorted({e["file"] for e, _ in fragments}),
                count=sum(len(v) for _, v in fragments),
                evidence={"examples": [{"on": qname(tbox, e["subject"]),
                                        "missing": sorted({f"{x['path_label']} {x['constraint']}"
                                                           for x in v})[:6]}
                                       for e, v in fragments[:30]]},
                fix="Complete the examples, or mark them as fragments.")
    ctx.finish("R7", "Documentation integrity and self-examples",
               summary=(f"{len(mentions)} undeclared terms named in the documentation; "
                        f"{len(examples)} Turtle examples, {failing} show an instance of their own "
                        f"class that fails the artifact's shapes, {len(fragments)} more are "
                        "incomplete fragments."),
               notes={"token_rules": TOKEN_RULES, "examples_parsed": len(examples)})
