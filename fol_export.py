"""
FOL export for the FOL-BFO-OWL tester.

Turns an OWL ontology's class structure into a *provable* first-order theory and
renders it in two interchange syntaxes:

  - Prover9 / LADR  (for the bundled prover cross-check, see prover9_runner.py)
  - CLIF            (ISO Common Logic Interchange Format, the syntax BFO 2020 /
                     ISO/IEC 21838-2 itself is axiomatized in)

Unlike the old toy export (which emitted only bare instance_of membership
predicates and so derived nothing), this emits the two axiom families a prover
needs to reproduce the OWL reasoner's coherence verdict:

  - Subsumptions   for Sub subclass-of Super
  - Disjointness   for every BFO category pair that clashes and is referenced by
                   the ontology, plus any disjointness asserted in the file.

BFO-2020 temporalization (SPEC Task 5): continuants take time-indexed
instantiation instance_of(x, C, t); occurrents take atemporal instantiation
instance_of_at(x, O), because an occurrent carries its temporal parts
intrinsically. A class's arity is decided by whether it sits under BFO_0000002
(continuant) or BFO_0000003 (occurrent) in the catalog.

The module reuses the same rdflib parse strategy as bfo_lint / external_reasoner
and the bfo/ catalog. It calls no DL reasoner.
"""
import logging
import re

import rdflib
from rdflib.namespace import RDFS, OWL

logger = logging.getLogger(__name__)

# BFO upper-category roots used to decide a class's temporal arity.
_BFO_PREFIX = "http://purl.obolibrary.org/obo/BFO_"
_CONTINUANT = "http://purl.obolibrary.org/obo/BFO_0000002"
_OCCURRENT = "http://purl.obolibrary.org/obo/BFO_0000003"

# Predicate names in the exported theory.
_P_CONT = "instance_of"      # ternary:  instance_of(X, Class, T)
_P_OCC = "instance_of_at"    # binary:   instance_of_at(X, Class)


def _local_name(uri):
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[1]
    if "/" in s:
        tail = s.rsplit("/", 1)[1]
        if tail:
            return tail
    return s


class _Symbols:
    """Maps ontology IRIs to safe, unique lower-case logic constants.

    Prover9 (with prolog_style_variables) treats capitalized tokens as variables,
    so class/relation constants must start lower-case. CLIF is more permissive but
    we reuse the same symbols for a single readable mapping across both syntaxes.
    """

    def __init__(self):
        self._by_iri = {}
        self._used = set()

    def get(self, iri, label=None):
        if iri in self._by_iri:
            return self._by_iri[iri]
        base = label or _local_name(iri)
        sym = re.sub(r"[^0-9a-zA-Z_]", "_", str(base)).strip("_").lower()
        if not sym or not sym[0].isalpha():
            sym = "c_" + sym if sym else "c"
        candidate = sym
        i = 2
        while candidate in self._used:
            candidate = f"{sym}_{i}"
            i += 1
        self._used.add(candidate)
        self._by_iri[iri] = candidate
        return candidate


class FolTheory:
    """A renderable first-order theory extracted from an ontology.

    Attributes:
        classes:      iri -> {sym, label, kind} where kind in
                      {'continuant', 'occurrent', 'unknown'}.
        subsumptions: list of (sub_iri, super_iri).
        disjoints:    list of (a_iri, b_iri, origin) where origin is
                      'asserted' (in the file) or 'bfo' (BFO disjointness closure).
        properties:   list of (iri, sym, label).
        bfo_path:     the BFO file used (for provenance in headers), or None.
    """

    def __init__(self):
        self.classes = {}
        self.subsumptions = []
        self.disjoints = []
        self.properties = []
        self.bfo_path = None

    # -- stats ---------------------------------------------------------------
    def stats(self):
        kinds = {"continuant": 0, "occurrent": 0, "unknown": 0}
        for c in self.classes.values():
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        return {
            "classes": len(self.classes),
            "continuants": kinds["continuant"],
            "occurrents": kinds["occurrent"],
            "unknown_kind": kinds["unknown"],
            "subsumptions": len(self.subsumptions),
            "disjoint_axioms": len(self.disjoints),
            "properties": len(self.properties),
        }

    def class_symbols(self):
        """name -> {sym, kind, label, iri} for every named class, for the runner."""
        out = {}
        for iri, c in self.classes.items():
            out[c["sym"]] = {"sym": c["sym"], "kind": c["kind"],
                             "label": c["label"], "iri": iri}
        return out


def _build_subclass_edges(graph):
    """child_iri -> set(parent_iri) over named (URIRef) rdfs:subClassOf edges."""
    edges = {}
    for s, _, o in graph.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            edges.setdefault(str(s), set()).add(str(o))
    return edges


def _bfo_parents(cls_iri, edges):
    """BFO category IRIs reached by walking subclass edges up from cls_iri.

    Stops expanding once a BFO node is reached (the catalog supplies BFO's own
    ancestry beyond that point).
    """
    seen, stack, bfo = set(), [cls_iri], set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for parent in edges.get(node, ()):
            if parent.startswith(_BFO_PREFIX):
                bfo.add(parent)
            else:
                stack.append(parent)
    return bfo


def _classify(cls_iri, edges, catalog):
    """Return 'continuant' | 'occurrent' | 'unknown' for a class IRI."""
    if cls_iri.startswith(_BFO_PREFIX):
        anc = catalog.ancestors(cls_iri) if catalog else {cls_iri}
    else:
        anc = set()
        for bfo_iri in _bfo_parents(cls_iri, edges):
            anc |= (catalog.ancestors(bfo_iri) if catalog else {bfo_iri})
    is_cont = _CONTINUANT in anc
    is_occ = _OCCURRENT in anc
    if is_cont and not is_occ:
        return "continuant"
    if is_occ and not is_cont:
        return "occurrent"
    return "unknown"


def build_theory(file_path=None, graph=None, catalog=None, bfo_path=None):
    """Extract a FolTheory from an OWL file or an already-parsed rdflib graph.

    Either file_path or graph must be given. catalog is a bfo.catalog.BfoCatalog;
    when omitted it is loaded lazily. BFO disjointness is included only for the
    categories the ontology actually references, keeping the export focused.
    """
    if catalog is None:
        try:
            from bfo import load_catalog
            catalog = load_catalog(bfo_path) if bfo_path else load_catalog()
        except Exception as e:  # noqa: BLE001
            logger.warning("FOL export: BFO catalog unavailable (%s); "
                           "temporal arity will be 'unknown'", e)
            catalog = None

    if graph is None:
        if not file_path:
            raise ValueError("build_theory needs file_path or graph")
        graph = rdflib.Graph()
        graph.parse(file_path)

    theory = FolTheory()
    theory.bfo_path = bfo_path
    syms = _Symbols()
    edges = _build_subclass_edges(graph)

    def label_of(iri):
        if catalog and catalog.is_bfo_iri(iri):
            return catalog.label_for(iri)
        return _local_name(iri)

    def register_class(iri):
        if iri in theory.classes:
            return theory.classes[iri]
        label = label_of(iri)
        rec = {
            "sym": syms.get(iri, label),
            "label": label,
            "kind": _classify(iri, edges, catalog),
        }
        theory.classes[iri] = rec
        return rec

    # 1. Named classes declared in the file.
    declared = set()
    for s, _, o in graph.triples((None, rdflib.RDF.type, OWL.Class)):
        if isinstance(s, rdflib.URIRef):
            declared.add(str(s))
    # Also anything appearing on either side of a named subClassOf edge.
    for child, parents in edges.items():
        declared.add(child)
        declared.update(parents)

    for iri in sorted(declared):
        name = _local_name(iri)
        if name in ("Thing", "Nothing", "Class"):
            continue
        register_class(iri)

    # 2. Subsumptions (named subClassOf edges, including user -> BFO category).
    for child, parents in edges.items():
        if child not in theory.classes:
            continue
        for parent in parents:
            if parent not in theory.classes:
                continue
            theory.subsumptions.append((child, parent))

    # 3. Disjointness asserted in the file (owl:disjointWith + AllDisjointClasses).
    asserted = set()
    for s, _, o in graph.triples((None, OWL.disjointWith, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            register_class(str(s))
            register_class(str(o))
            asserted.add(frozenset((str(s), str(o))))
    for axiom in graph.subjects(rdflib.RDF.type, OWL.AllDisjointClasses):
        members = []
        for _, _, lst in graph.triples((axiom, OWL.members, None)):
            members = [str(m) for m in rdflib.collection.Collection(graph, lst)
                       if isinstance(m, rdflib.URIRef)]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                register_class(members[i])
                register_class(members[j])
                asserted.add(frozenset((members[i], members[j])))
    for pair in asserted:
        a, b = tuple(pair)
        theory.disjoints.append((a, b, "asserted"))

    # 4. BFO disjointness, restricted to the BFO categories this ontology
    #    references as subclass parents. This is what lets the prover rediscover
    #    a partition straddle (e.g. Quality vs Disposition for Force).
    if catalog is not None:
        referenced_bfo = sorted({
            p for parents in edges.values() for p in parents
            if p.startswith(_BFO_PREFIX)
        })
        for iri in referenced_bfo:
            register_class(iri)
        for i in range(len(referenced_bfo)):
            for j in range(i + 1, len(referenced_bfo)):
                a, b = referenced_bfo[i], referenced_bfo[j]
                if catalog.clash(a, b) and frozenset((a, b)) not in asserted:
                    theory.disjoints.append((a, b, "bfo"))

    # 5. Object properties (binary relations; signatures are out of scope here).
    for s, _, o in graph.triples((None, rdflib.RDF.type, OWL.ObjectProperty)):
        if isinstance(s, rdflib.URIRef):
            iri = str(s)
            theory.properties.append((iri, syms.get(iri, _local_name(iri)),
                                      label_of(iri)))

    return theory


# -- rendering ---------------------------------------------------------------

def _membership_p9(kind, var, sym, t="T"):
    if kind == "occurrent":
        return f"{_P_OCC}({var},{sym})"
    return f"{_P_CONT}({var},{sym},{t})"


def render_prover9(theory):
    """Render the theory as a runnable Prover9 (LADR) input file."""
    lines = [
        "% FOL export of an OWL ontology for Prover9 / Mace4.",
        "% Generated by the FOL-BFO-OWL tester (fol_export.py).",
        "% Continuants: instance_of(x, C, t)   Occurrents: instance_of_at(x, O)",
        "set(prolog_style_variables).",
        "",
        "formulas(assumptions).",
    ]

    def kind(iri):
        return theory.classes[iri]["kind"]

    def sym(iri):
        return theory.classes[iri]["sym"]

    if theory.subsumptions:
        lines.append("  % --- Subsumptions (SubClassOf) ---")
    for sub, sup in theory.subsumptions:
        ks, ku = kind(sub), kind(sup)
        note = ""
        if ks == "occurrent" and ku == "occurrent":
            body = (f"all X ({_membership_p9('occurrent','X',sym(sub))} -> "
                    f"{_membership_p9('occurrent','X',sym(sup))}).")
        else:
            # Default to the time-indexed (continuant) form. A continuant/occurrent
            # mismatch is itself a modeling error the lint flags; we mark it.
            if ks != ku and "unknown" not in (ks, ku):
                note = "  % NOTE category mismatch between sub and super"
            body = (f"all X all T ({_membership_p9('continuant','X',sym(sub))} -> "
                    f"{_membership_p9('continuant','X',sym(sup))}).")
        lines.append(f"  {body}{note}")

    if theory.disjoints:
        lines.append("  % --- Disjointness ---")
    for a, b, origin in theory.disjoints:
        ka, kb = kind(a), kind(b)
        tag = "BFO" if origin == "bfo" else "asserted"
        if ka == "occurrent" and kb == "occurrent":
            body = (f"all X (-({_membership_p9('occurrent','X',sym(a))} & "
                    f"{_membership_p9('occurrent','X',sym(b))})).")
        else:
            body = (f"all X all T (-({_membership_p9('continuant','X',sym(a))} & "
                    f"{_membership_p9('continuant','X',sym(b))})).")
        lines.append(f"  {body}  % {tag}: {theory.classes[a]['label']} / "
                     f"{theory.classes[b]['label']}")

    lines.append("end_of_list.")
    return "\n".join(lines) + "\n"


def render_clif(theory):
    """Render the theory in ISO Common Logic Interchange Format (CLIF)."""
    lines = [
        ";; FOL export of an OWL ontology in Common Logic Interchange Format.",
        ";; Generated by the FOL-BFO-OWL tester (fol_export.py).",
        ";; Continuants: (instance_of x C t)   Occurrents: (instance_of_at x O)",
        "(cl-text ontology-export",
    ]

    def kind(iri):
        return theory.classes[iri]["kind"]

    def sym(iri):
        return theory.classes[iri]["sym"]

    def member(k, var, s, t="t"):
        if k == "occurrent":
            return f"({_P_OCC} {var} {s})"
        return f"({_P_CONT} {var} {s} {t})"

    if theory.subsumptions:
        lines.append("  ;; --- Subsumptions (SubClassOf) ---")
    for sub, sup in theory.subsumptions:
        ks, ku = kind(sub), kind(sup)
        if ks == "occurrent" and ku == "occurrent":
            lines.append(f"  (forall (x) (if {member('occurrent','x',sym(sub))} "
                         f"{member('occurrent','x',sym(sup))}))")
        else:
            lines.append(f"  (forall (x t) (if {member('continuant','x',sym(sub))} "
                         f"{member('continuant','x',sym(sup))}))")

    if theory.disjoints:
        lines.append("  ;; --- Disjointness ---")
    for a, b, origin in theory.disjoints:
        ka, kb = kind(a), kind(b)
        tag = "BFO" if origin == "bfo" else "asserted"
        if ka == "occurrent" and kb == "occurrent":
            lines.append(f"  (forall (x) (not (and {member('occurrent','x',sym(a))} "
                         f"{member('occurrent','x',sym(b))})))  ;; {tag}")
        else:
            lines.append(f"  (forall (x t) (not (and {member('continuant','x',sym(a))} "
                         f"{member('continuant','x',sym(b))})))  ;; {tag}")

    lines.append(")")
    return "\n".join(lines) + "\n"


def generate_exports(file_path=None, graph=None, catalog=None, bfo_path=None):
    """Convenience: build the theory and return both renderings plus stats.

    Returns {'prover9': str, 'clif': str, 'stats': dict, 'theory': FolTheory}.
    Never raises for ordinary extraction problems; on failure returns a dict with
    'error' set and empty renderings so callers can degrade gracefully.
    """
    try:
        theory = build_theory(file_path=file_path, graph=graph,
                              catalog=catalog, bfo_path=bfo_path)
        return {
            "prover9": render_prover9(theory),
            "clif": render_clif(theory),
            "stats": theory.stats(),
            "theory": theory,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("FOL export failed: %s", e)
        return {"prover9": "", "clif": "", "stats": {}, "theory": None,
                "error": f"{type(e).__name__}: {e}"}
