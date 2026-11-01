"""The quality layer (SPEC-release.md, section 9.5): starters the author edits.

QC queries in the LOF form (``*-violation.sparql``: any result fails
``robot verify``), competency-question starters, and a SHACL scaffold from the
ontology's axioms (``shacl_tools.generate_shapes``) to review.
"""

from . import docs

QC = {
    "missing-label": ("Own terms without an rdfs:label.", """
SELECT DISTINCT ?term WHERE {
  VALUES ?type { owl:Class owl:ObjectProperty owl:DatatypeProperty }
  ?term a ?type .
  FILTER(STRSTARTS(STR(?term), "{{ns}}"))
  FILTER NOT EXISTS { ?term rdfs:label ?label }
}"""),
    "missing-definition": ("Own terms without a definition (skos:definition or IAO:0000115).", """
SELECT DISTINCT ?term WHERE {
  VALUES ?type { owl:Class owl:ObjectProperty owl:DatatypeProperty }
  ?term a ?type .
  FILTER(STRSTARTS(STR(?term), "{{ns}}"))
  FILTER NOT EXISTS { ?term skos:definition ?d }
  FILTER NOT EXISTS { ?term obo:IAO_0000115 ?d }
}"""),
    "duplicate-label": ("Two own terms with the same label.", """
SELECT DISTINCT ?a ?b ?label WHERE {
  ?a rdfs:label ?label .
  ?b rdfs:label ?label .
  FILTER(STRSTARTS(STR(?a), "{{ns}}") && STRSTARTS(STR(?b), "{{ns}}") && STR(?a) < STR(?b))
}"""),
    "iri-pattern": ("Terms under the project's base that do not follow the term IRI pattern.", """
SELECT DISTINCT ?term WHERE {
  VALUES ?type { owl:Class owl:ObjectProperty owl:DatatypeProperty owl:NamedIndividual }
  ?term a ?type .
  FILTER(STRSTARTS(STR(?term), "{{stem}}") && !STRSTARTS(STR(?term), "{{ns}}"))
}"""),
    "no-bfo-ancestor": ("Own classes with no BFO ancestor.", """
SELECT DISTINCT ?term WHERE {
  ?term a owl:Class .
  FILTER(STRSTARTS(STR(?term), "{{ns}}"))
  FILTER NOT EXISTS {
    ?term rdfs:subClassOf* ?bfo .
    FILTER(STRSTARTS(STR(?bfo), "http://purl.obolibrary.org/obo/BFO_"))
  }
}"""),
}
PREFIXES = """PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
"""


def qc_queries(a, term_ns):
    """{filename: text}. The term namespace and project stem are validated IRIs."""
    stem = a["base"].rsplit("/", 1)[0] + "/"
    out = {}
    for key, (title, body) in QC.items():
        if key == "no-bfo-ancestor" and a["bfo"] == "none":
            continue
        text = body.replace("{{ns}}", term_ns).replace("{{stem}}", stem)
        out[f"{key}-violation.sparql"] = f"# LOF-style QC check: {title}\n# Any result fails `make test`.\n{PREFIXES}{text.strip()}\n"
    return out


def run_qc(g, queries):
    """Each query's result count on ``g`` (rdflib, offline)."""
    out = {}
    for name, text in sorted(queries.items()):
        try:
            out[name] = len(list(g.query(text)))
        except Exception as e:  # noqa: BLE001 - a broken starter is reported, not fatal
            out[name] = f"error: {e}"
    return out


def cq_starters(a):
    questions = [f"What kinds of entity does {a['title']} distinguish?",
                 "Which classes have no subclasses (the most specific kinds)?"]
    return {f"cq-{i:03d}.sparql": docs.render("cq.sparql", n=str(i), question=q)
            for i, q in enumerate(questions, 1)}


def shapes_scaffold(g, a):
    """Turtle for a SHACL scaffold, or None when the ontology gives nothing to shape."""
    import shacl_tools
    try:
        res = shacl_tools.generate_shapes(g)
    except Exception:  # noqa: BLE001 - the scaffold is optional
        return None
    text = (res or {}).get("turtle") or ""
    if not text.strip() or not res.get("node_shapes"):
        return None
    return (f"# SHACL scaffold for {a['title']} {a['version']}, generated from the ontology's axioms.\n"
            "# Review every shape before relying on it: it states what the axioms imply, not what\n"
            "# the data must contain.\n" + text)
