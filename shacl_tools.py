"""SHACL support: derive shapes from an ontology, validate data against shapes.

Three operations, all pure functions over rdflib graphs (no Flask):

* ``generate_shapes`` -- scaffold a SHACL shapes graph from an OWL ontology's
  restrictions, domains/ranges and functional properties, so shapes start from
  what the ontology already says instead of a blank page.
* ``validate`` -- run pySHACL over a data graph (the ontology's own individuals,
  pasted instance data, or both) with the ontology mixed in as ``ont_graph`` so
  ``sh:class`` sees the class hierarchy. Results come back as plain dicts with
  human-readable labels.
* ``lint_shapes`` -- check a shapes graph against the SHACL-SHACL meta-shapes
  and against the ontology (targets, classes and paths that the ontology never
  declares are almost always typos or stale IRIs).

OWL is open-world and SHACL is closed-world: an OWL ``some`` restriction says an
instance *has* such a value somewhere, a SHACL ``qualifiedMinCount 1`` demands
the value be *present in the data*. Generated shapes therefore read OWL axioms
as data-completeness requirements, which is usually what a shape author wants
but is a choice, and the generated graph says so in its header comment.
"""

import logging
import re

import rdflib
from rdflib import BNode, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

logger = logging.getLogger(__name__)

MAX_INPUT_BYTES = 4 * 1024 * 1024
RDF_FORMATS = ("turtle", "xml", "json-ld", "nt", "n3", "trig")
INFERENCE_MODES = ("none", "rdfs", "owlrl", "both")
_SKIP_CLASSES = {OWL.Thing, OWL.Nothing}


# -- parsing / labels -----------------------------------------------------------

def parse_rdf(text, fmt=None):
    """Parse RDF text, trying ``fmt`` first then the common syntaxes.
    Raises ValueError with the first parser's message if none succeed."""
    if text is None or not text.strip():
        raise ValueError("empty RDF input")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"RDF input exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MB")
    order = [fmt] if fmt else []
    order += [f for f in RDF_FORMATS if f != fmt]
    first_err = None
    for f in order:
        g = rdflib.Graph()
        try:
            g.parse(data=text, format=f)
            return g
        except Exception as exc:  # noqa: BLE001 - try the next syntax
            first_err = first_err or f"{f}: {exc}"
    raise ValueError(f"could not parse RDF ({first_err})")


def load_ontology_graph(path):
    from owl_format_detector import parse_rdf_file
    return parse_rdf_file(path)


def tbox_only(onto):
    """Copy of ``onto`` without its individuals (any subject typed by something
    outside the RDF/RDFS/OWL vocabularies, or declared owl:NamedIndividual)."""
    meta = (str(RDF), str(RDFS), str(OWL))
    individuals = {
        s for s, t in onto.subject_objects(RDF.type)
        if t == OWL.NamedIndividual or not str(t).startswith(meta)
    }
    out = rdflib.Graph()
    for prefix, ns in onto.namespaces():
        out.bind(prefix, ns, override=False)
    for t in onto:
        if t[0] not in individuals:
            out.add(t)
    return out


def local_name(iri):
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            tail = s.rsplit(sep, 1)[1]
            if tail:
                return tail
    return s


def label_map(*graphs):
    """IRI -> preferred label (rdfs:label, then skos:prefLabel; English or
    untagged first) across the given graphs."""
    best = {}
    for g in graphs:
        if g is None:
            continue
        for prio, pred in enumerate((RDFS.label, SKOS.prefLabel, SH.name)):
            for s, o in g.subject_objects(pred):
                if not isinstance(s, URIRef) or not isinstance(o, Literal) or not str(o).strip():
                    continue
                lang = (o.language or "").lower()
                key = (prio, 0 if lang in ("", "en") or lang.startswith("en-") else 1)
                if s not in best or key < best[s][0]:
                    best[s] = (key, str(o).strip())
    return {iri: text for iri, (_, text) in best.items()}


def display(node, labels):
    """Human-readable rendering of a node for reports."""
    if node is None:
        return None
    if isinstance(node, URIRef):
        return labels.get(node) or local_name(node)
    if isinstance(node, Literal):
        return str(node)
    return "[blank node]"


# -- generation -----------------------------------------------------------------

def _shape_ns(onto):
    for s in onto.subjects(RDF.type, OWL.Ontology):
        if isinstance(s, URIRef):
            base = str(s).rstrip("/#")
            return rdflib.Namespace(base + "/shapes#")
    return rdflib.Namespace("urn:owltester:shapes#")


def _safe_id(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", text) or "x"


def _is_datatype(onto, node):
    return isinstance(node, URIRef) and (
        str(node).startswith(str(XSD)) or node == RDFS.Literal
        or (node, RDF.type, RDFS.Datatype) in onto)


def _is_data_property(onto, prop):
    return isinstance(prop, URIRef) and (prop, RDF.type, OWL.DatatypeProperty) in onto


def _members(g, lst):
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001 - malformed list
        return []


class _Builder:
    """Accumulates shapes into ``self.g`` and remembers what it could not map."""

    def __init__(self, onto):
        self.onto = onto
        self.g = rdflib.Graph()
        self.ns = _shape_ns(onto)
        self.g.bind("sh", SH)
        self.g.bind("xsd", XSD)
        self.g.bind("shape", self.ns)
        for prefix, ns in onto.namespaces():
            if prefix and prefix not in ("sh", "shape"):
                self.g.bind(prefix, ns, override=False)
        self.labels = label_map(onto)
        self.skipped = []
        self.node_shapes = {}
        self.property_shape_count = 0

    def name(self, iri):
        return self.labels.get(iri) or local_name(iri)

    def node_shape(self, cls):
        if cls not in self.node_shapes:
            shape = self.ns[_safe_id(local_name(cls)) + "Shape"]
            self.g.add((shape, RDF.type, SH.NodeShape))
            self.g.add((shape, SH.targetClass, cls))
            self.g.add((shape, RDFS.label, Literal(f"{self.name(cls)} shape")))
            self.node_shapes[cls] = shape
        return self.node_shapes[cls]

    def path(self, prop):
        """sh:path for a property expression, or None if it is not mappable."""
        if isinstance(prop, URIRef):
            return prop
        inv = self.onto.value(prop, OWL.inverseOf)
        if isinstance(inv, URIRef):
            node = BNode()
            self.g.add((node, SH.inversePath, inv))
            return node
        return None

    def value_constraint(self, target, filler):
        """Constrain values at ``target`` to ``filler`` (class/datatype/union/
        intersection of named things). Returns False if not expressible."""
        if filler is None or filler in _SKIP_CLASSES:
            return True
        if isinstance(filler, URIRef):
            pred = SH.datatype if _is_datatype(self.onto, filler) else SH["class"]
            self.g.add((target, pred, filler))
            return True
        comp = self.onto.value(filler, OWL.complementOf)
        if isinstance(comp, URIRef):
            n = BNode()
            pred = SH.datatype if _is_datatype(self.onto, comp) else SH["class"]
            self.g.add((n, pred, comp))
            self.g.add((target, SH["not"], n))
            return True
        for op, sh_op in ((OWL.unionOf, SH["or"]), (OWL.intersectionOf, SH["and"])):
            lst = self.onto.value(filler, op)
            if lst is None:
                continue
            members = _members(self.onto, lst)
            if not members or not all(isinstance(m, URIRef) for m in members):
                return False
            nodes = []
            for m in members:
                n = BNode()
                pred = SH.datatype if _is_datatype(self.onto, m) else SH["class"]
                self.g.add((n, pred, m))
                nodes.append(n)
            head = BNode()
            Collection(self.g, head, nodes)
            self.g.add((target, sh_op, head))
            return True
        return False

    def property_shape(self, shape, path, prop):
        ps = BNode()
        self.g.add((shape, SH.property, ps))
        self.g.add((ps, SH.path, path))
        if isinstance(prop, URIRef):
            self.g.add((ps, SH.name, Literal(self.name(prop))))
        self.property_shape_count += 1
        return ps

    def restriction(self, cls, r):
        o = self.onto
        prop = o.value(r, OWL.onProperty)
        path = self.path(prop) if prop is not None else None
        desc = f"{self.name(cls)}: restriction on {display(prop, self.labels) if prop is not None else '?'}"
        if path is None:
            self.skipped.append(f"{desc} (property expression not mappable to sh:path)")
            return
        shape = self.node_shape(cls)

        some = o.value(r, OWL.someValuesFrom)
        only = o.value(r, OWL.allValuesFrom)
        has_value = o.value(r, OWL.hasValue)
        on_class = o.value(r, OWL.onClass) or o.value(r, OWL.onDataRange)
        cards = {k: o.value(r, p) for k, p in (
            ("min", OWL.minQualifiedCardinality), ("max", OWL.maxQualifiedCardinality),
            ("exact", OWL.qualifiedCardinality), ("umin", OWL.minCardinality),
            ("umax", OWL.maxCardinality), ("uexact", OWL.cardinality))}

        if some is not None:
            ps = self.property_shape(shape, path, prop)
            if some in _SKIP_CLASSES:
                self.g.add((ps, SH.minCount, Literal(1)))
                return
            qvs = BNode()
            if not self.value_constraint(qvs, some):
                self.g.remove((shape, SH.property, ps))
                self.skipped.append(f"{desc} (complex 'some' filler)")
                return
            self.g.add((ps, SH.qualifiedValueShape, qvs))
            self.g.add((ps, SH.qualifiedMinCount, Literal(1)))
        elif only is not None:
            ps = self.property_shape(shape, path, prop)
            if not self.value_constraint(ps, only):
                self.g.remove((shape, SH.property, ps))
                self.skipped.append(f"{desc} (complex 'only' filler)")
        elif has_value is not None:
            ps = self.property_shape(shape, path, prop)
            self.g.add((ps, SH.hasValue, has_value))
        elif any(v is not None for v in cards.values()):
            ps = self.property_shape(shape, path, prop)
            qualified = on_class is not None and on_class not in _SKIP_CLASSES
            lo = cards["min"] or cards["exact"] or cards["umin"] or cards["uexact"]
            hi = cards["max"] or cards["exact"] or cards["umax"] or cards["uexact"]
            if qualified:
                qvs = BNode()
                if not self.value_constraint(qvs, on_class):
                    self.g.remove((shape, SH.property, ps))
                    self.skipped.append(f"{desc} (complex cardinality filler)")
                    return
                self.g.add((ps, SH.qualifiedValueShape, qvs))
                lo_p, hi_p = SH.qualifiedMinCount, SH.qualifiedMaxCount
            else:
                lo_p, hi_p = SH.minCount, SH.maxCount
            if lo is not None:
                self.g.add((ps, lo_p, Literal(int(lo))))
            if hi is not None:
                self.g.add((ps, hi_p, Literal(int(hi))))
        else:
            self.skipped.append(f"{desc} (unsupported restriction kind)")

    def class_axioms(self, cls):
        o = self.onto
        sources = list(o.objects(cls, RDFS.subClassOf))
        for eq in o.objects(cls, OWL.equivalentClass):
            lst = o.value(eq, OWL.intersectionOf)
            sources.extend(_members(o, lst) if lst is not None else [eq])
        for node in sources:
            if isinstance(node, BNode) and o.value(node, OWL.onProperty) is not None:
                self.restriction(cls, node)

    def property_axioms(self, prop):
        o = self.onto
        domain = o.value(prop, RDFS.domain)
        rng = o.value(prop, RDFS.range)
        functional = (prop, RDF.type, OWL.FunctionalProperty) in o
        if domain is None and rng is None and not functional:
            return
        shape = self.ns[_safe_id(local_name(prop)) + "UsageShape"]
        self.g.add((shape, RDF.type, SH.NodeShape))
        self.g.add((shape, SH.targetSubjectsOf, prop))
        self.g.add((shape, RDFS.label, Literal(f"Usage of {self.name(prop)}")))
        if domain is not None and domain not in _SKIP_CLASSES:
            if not self.value_constraint(shape, domain):
                self.skipped.append(f"{self.name(prop)}: complex domain")
        if rng is not None or functional:
            ps = self.property_shape(shape, prop, prop)
            if functional:
                self.g.add((ps, SH.maxCount, Literal(1)))
            if rng is not None and rng not in _SKIP_CLASSES:
                if not self.value_constraint(ps, rng):
                    self.skipped.append(f"{self.name(prop)}: complex range")
        self.node_shapes.setdefault(prop, shape)


def generate_shapes(onto, include_domain_range=True):
    """Derive a SHACL shapes graph from an ontology graph.

    Returns ``{"turtle", "node_shapes", "property_shapes", "skipped"}`` where
    ``skipped`` lists OWL axioms that have no faithful SHACL rendering here
    (nested anonymous fillers, property chains as paths, ...).
    """
    b = _Builder(onto)
    for cls in sorted(set(onto.subjects(RDF.type, OWL.Class)), key=str):
        if isinstance(cls, URIRef) and cls not in _SKIP_CLASSES:
            b.class_axioms(cls)
    if include_domain_range:
        props = set(onto.subjects(RDF.type, OWL.ObjectProperty)) | \
            set(onto.subjects(RDF.type, OWL.DatatypeProperty))
        for prop in sorted(props, key=str):
            if isinstance(prop, URIRef):
                b.property_axioms(prop)

    header = (
        "# SHACL shapes generated by OwlTesterService from the ontology's OWL axioms.\n"
        "# OWL is open-world; these shapes read 'some' and cardinality restrictions as\n"
        "# closed-world data-completeness requirements. Edit freely.\n"
    )
    for line in b.skipped:
        header += f"# skipped: {line}\n"
    turtle = b.g.serialize(format="turtle")
    return {
        "turtle": header + "\n" + turtle,
        "node_shapes": len(b.node_shapes),
        "property_shapes": b.property_shape_count,
        "skipped": b.skipped,
    }


# -- validation -------------------------------------------------------------------

def validate(data_graph, shapes_graph, ont_graph=None, inference="rdfs"):
    """Validate ``data_graph`` against ``shapes_graph`` with pySHACL.

    ``ont_graph`` is mixed into the data graph by pySHACL, so the ontology's
    class hierarchy (and, with OWL-RL inference, more) is visible to sh:class.
    """
    import pyshacl

    if inference not in INFERENCE_MODES:
        raise ValueError(f"inference must be one of {', '.join(INFERENCE_MODES)}")
    conforms, results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ont_graph,
        inference=inference,
        abort_on_first=False,
        allow_warnings=True,
        advanced=True,
    )
    labels = label_map(ont_graph, shapes_graph, data_graph)
    results = []
    for r in results_graph.subjects(RDF.type, SH.ValidationResult):
        val = results_graph.value
        severity = val(r, SH.resultSeverity)
        component = val(r, SH.sourceConstraintComponent)
        path = val(r, SH.resultPath)
        results.append({
            "severity": local_name(severity) if severity is not None else "Violation",
            "focus_node": str(val(r, SH.focusNode)),
            "focus_label": display(val(r, SH.focusNode), labels),
            "path": str(path) if isinstance(path, URIRef) else None,
            "path_label": display(path, labels) if path is not None else None,
            "value": display(val(r, SH.value), labels),
            "message": str(val(r, SH.resultMessage) or ""),
            "constraint": local_name(component).replace("ConstraintComponent", "") if component else None,
            "source_shape": display(val(r, SH.sourceShape), labels),
        })
    order = {"Violation": 0, "Warning": 1, "Info": 2}
    results.sort(key=lambda x: (order.get(x["severity"], 3), x["focus_label"] or "", x["path_label"] or ""))
    counts = {}
    for x in results:
        counts[x["severity"]] = counts.get(x["severity"], 0) + 1
    return {
        "conforms": bool(conforms),
        "results": results,
        "counts": counts,
        "report_text": results_text[:20000],
    }


# -- shape lint ---------------------------------------------------------------------

def _declared(onto):
    out = set()
    for t in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
              RDFS.Class, RDF.Property, OWL.NamedIndividual, RDFS.Datatype):
        out.update(s for s in onto.subjects(RDF.type, t) if isinstance(s, URIRef))
    return out


def lint_shapes(shapes_graph, onto=None):
    """Problems with a shapes graph itself.

    Returns a list of ``{"level", "message"}``: SHACL-SHACL syntax violations
    (malformed shapes) and, given ``onto``, targets/classes/paths that the
    ontology does not declare.
    """
    import pyshacl
    from pyshacl.errors import ReportableRuntimeError

    issues = []
    try:
        pyshacl.validate(rdflib.Graph(), shacl_graph=shapes_graph, meta_shacl=True)
    except ReportableRuntimeError as exc:
        issues.append({"level": "error", "message": f"Shapes graph is not valid SHACL: {exc.message[:800]}"})
    except Exception as exc:  # noqa: BLE001 - pySHACL raises bare errors for broken lists etc.
        issues.append({"level": "error", "message": f"Shapes graph could not be loaded: {str(exc)[:800]}"})

    shapes = set(shapes_graph.subjects(RDF.type, SH.NodeShape)) | \
        set(shapes_graph.subjects(RDF.type, SH.PropertyShape))
    if not shapes:
        issues.append({"level": "warning", "message": "No sh:NodeShape or sh:PropertyShape found."})
    for s in shapes:
        has_target = any(shapes_graph.value(s, p) is not None for p in (
            SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf, SH.target))
        is_class_shape = (s, RDF.type, RDFS.Class) in shapes_graph or (s, RDF.type, OWL.Class) in shapes_graph
        referenced = (None, SH.node, s) in shapes_graph or (None, SH.qualifiedValueShape, s) in shapes_graph
        if not (has_target or is_class_shape or referenced) and isinstance(s, URIRef):
            issues.append({"level": "warning",
                           "message": f"Shape {local_name(s)} has no target, so it never fires."})

    if onto is not None:
        known = _declared(onto) | _declared(shapes_graph)
        labels = label_map(onto)
        checks = ((SH.targetClass, "target class"), (SH["class"], "sh:class"),
                  (SH.path, "sh:path"), (SH.targetSubjectsOf, "target property"),
                  (SH.targetObjectsOf, "target property"), (SH.inversePath, "inverse path"))
        seen = set()
        for pred, what in checks:
            for o in shapes_graph.objects(None, pred):
                if not isinstance(o, URIRef) or o in known or o in seen:
                    continue
                if str(o).startswith((str(RDF), str(RDFS), str(OWL), str(XSD), str(SKOS))):
                    continue
                seen.add(o)
                issues.append({"level": "warning",
                               "message": f"{what} {display(o, labels)} <{o}> is not declared in the ontology."})
    return issues
