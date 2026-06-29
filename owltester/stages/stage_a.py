"""Stage A — structural smoke test.

Cheap checks that catch the catastrophic "hollowed out" case immediately, before
any reasoner runs. This is the stage that turns the SOOL_autofixed.owl outcome
(6,881 declarations, 0 axioms) into a hard failure.
"""

import re

from rdflib import RDFS, URIRef

from ..model import StageResult
from .. import errors
from ..kernel import ANCHORS

# A6/D4 — privation/compound anti-pattern. Mirrors bfo-agent PC-1 (privation) and
# PC-2 (compound). Privation names a thing by what is absent; compound bundles
# several concepts into one class. Failure must be a typology *instance*, never a
# named class, so any of these as a class name is a hard fail.
_PRIVATION_RE = re.compile(
    r"(?i)^(absence|absent|lack|lacking|missing|non[A-Z_]|privation|deprivation|"
    r"failure|failureto|failureof|without|no[A-Z])"
)
_PRIVATION_SUBSTR = re.compile(
    r"(?i)(absenceof|lackof|failureof|failureto|nonexisten|noncompli)"
)
# compound: a CamelCase/underscore name chaining concepts via connectors.
_CONNECTOR_RE = re.compile(r"(?i)(with|and|of|by|over)")


def _local(iri):
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _is_privation(local):
    return bool(_PRIVATION_RE.match(local) or _PRIVATION_SUBSTR.search(local))


def _is_compound(local):
    # split CamelCase + underscores into tokens
    tokens = re.findall(r"[A-Z]+[a-z0-9]*|[a-z0-9]+", local)
    connectors = [t for t in tokens if _CONNECTOR_RE.fullmatch(t)]
    # a name with >=2 connectors (e.g. NormAlignmentWithRuleOfRecognition) bundles
    # multiple concepts and should be decomposed.
    return len(connectors) >= 2 and len(tokens) >= 5


def anti_pattern_hits(classes):
    """Return (privation_hits, compound_hits) as lists of local names."""
    priv, comp = [], []
    for iri in sorted(classes):
        local = _local(iri)
        if _is_privation(local):
            priv.append(local)
        elif _is_compound(local):
            comp.append(local)
    return priv, comp


def run(ctx):
    r = StageResult("A")
    c = ctx.counts
    k = ctx.kernel

    # A1 — at least one logical axiom.
    if c.axioms <= 0:
        r.add(errors.E_NO_AXIOMS,
              "Artifact has 0 logical axioms (declarations and labels do not count).")

    # A2 — non-trivial subClassOf present.
    if c.subClassOf <= 0:
        r.add(errors.E_FLAT, "No non-trivial rdfs:subClassOf axioms.")

    # A3 — object properties declared AND at least one object-property axiom.
    if c.objectProperties <= 0:
        r.add(errors.E_FLAT, "No owl:ObjectProperty declared.")
    elif c.objectPropertyAxioms <= 0:
        r.add(errors.E_FLAT,
              "Object properties are declared but never used in any axiom or "
              "assertion (declarations alone do not satisfy A3).")

    # A4 — BFO anchors present AND populated (>=1 subclass or instance under each).
    # Populated means some artifact class *reaches* the anchor via subClassOf*
    # (through SOoL categories the kernel grounds), or an individual is typed to
    # it. A bare anchor stub with nothing under it does not count.
    from rdflib import RDF
    populated = set()
    for cls in ctx.classes:
        for entry in ctx.bfo_parents(cls):
            populated.add(entry)
            if ctx.catalog is not None:
                populated |= ctx.catalog.ancestors(entry)
    type_objects = {str(o) for _, _, o in ctx.graph.triples((None, RDF.type, None))}
    missing = []
    for label, anchor in ANCHORS.items():
        if anchor not in populated and anchor not in type_objects:
            missing.append(label)
    if missing:
        r.add(errors.E_NO_BFO,
              "BFO anchor(s) absent or unpopulated: " + ", ".join(missing) +
              ". Bare BFO fragment stubs with nothing under them fail A4.")

    # A5 — class count within [kernel_size, kernel_size * max_factor].
    max_factor = float(ctx.kernel and 4 or 4)
    upper = int(k.size * 4)
    if k.size > 0 and c.classes > upper:
        r.add(errors.E_BLOATED,
              f"{c.classes} classes exceeds kernel x max_factor "
              f"({k.size} x 4 = {upper}).")
    r.notes["class_bounds"] = {"kernel_size": k.size, "upper": upper,
                               "classes": c.classes}

    # A6 — privation/compound anti-pattern.
    priv, comp = anti_pattern_hits(ctx.classes)
    hits = priv + comp
    if hits:
        for local in priv:
            r.add(errors.E_ANTIPATTERN,
                  f"'{local}' names a privation class. Failure/absence must be a "
                  f"typology instance, not a named class.", iri=local,
                  suggested_rewrite=f"instance of a contradiction/failure type, not class {local}")
        for local in comp:
            r.add(errors.E_ANTIPATTERN,
                  f"'{local}' is a compound class bundling several concepts; "
                  f"decompose it.", iri=local)
    r.notes["antipattern_hits"] = hits

    return r
