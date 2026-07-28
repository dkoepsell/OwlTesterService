"""Binding an ontology's entities to the loci of its recognition chain.

Nothing can be typed ``kernel x chain`` until we know which of the artifact's
classes sit at which locus. Two sources, in strict precedence:

1. **Declared** — a ``recog:hasChainLocus`` annotation in the artifact itself,
   or an override supplied by the user. Authoritative.
2. **Proposed** — inferred from BFO typing, disambiguated by label cues.
   Never authoritative, and always rendered as a proposal.

The proposer is deliberately unwilling to guess, and the rule it follows is
sharper than it first looks: **BFO type alone never assigns a locus.**

The temptation is to read type off to locus directly -- role to assessor,
process to act. It does not survive contact with a scientific ontology. A
depolarization is a BFO process and no part of anyone's recognition chain; a
neuron's role is not an assessor's licence. Typing every process as a candidate
recognition act would hand every gene ontology in existence a recognition chain
it does not have, and with it a stratum profile that is simply false.

So type only *corroborates*. A locus assignment needs a label cue; the BFO type
then confirms it (high confidence), fails to speak to it (low), or contradicts
it (low, and worth a look -- a class labelled "diagnostic criterion" but
grounded as a material entity is telling you something). Where the label names
more than one locus the entity is reported **ambiguous** rather than assigned.

Silent guessing here would corrupt every locus-indexed number downstream, which
is exactly the kind of unattributed inference the paper's §10 audit exists to
prevent.
"""

import re
from dataclasses import dataclass, field

from .kernel import LOCUS_KEYS

RECOG_NS = "https://ontology.davidkoepsell.com/recognition#"

# Annotation properties read as a declared binding. The bare local name is
# matched too, so an artifact may use its own namespace.
_LOCUS_PREDICATES = ("hasChainLocus", "chainLocus", "recognitionLocus")


# --- BFO type -> loci the type is compatible with ------------------------------
#
# Read as corroboration, not assignment: "an entity of this upper type could sit
# at these loci". Ordered most specific first; the first matching ancestor wins.
# Nothing in this table can place an entity on the chain by itself.

_BFO = "http://purl.obolibrary.org/obo/BFO_"
_IAO = "http://purl.obolibrary.org/obo/IAO_"

UPPER_PREFIXES = (_BFO, _IAO)

BFO_TYPE_LOCI = [
    (_IAO + "0000033", ("criteria",)),            # directive information entity
    (_BFO + "0000023", ("assessor", "effect")),   # role
    (_BFO + "0000034", ("effect",)),              # function
    (_BFO + "0000016", ("facts", "effect")),      # disposition
    (_BFO + "0000019", ("facts",)),               # quality
    (_BFO + "0000027", ("authority",)),           # object aggregate
    (_BFO + "0000015", ("act", "remedy")),        # process
    (_BFO + "0000017", ("effect",)),              # realizable entity
    (_IAO + "0000030", ("criteria",)),            # information content entity
    (_BFO + "0000031", ("criteria",)),            # generically dependent cont.
    (_BFO + "0000020", ("facts", "effect")),      # specifically dependent cont.
    (_BFO + "0000003", ("act", "remedy")),        # occurrent
]


# --- label cues ---------------------------------------------------------------
#
# Used only to disambiguate a multi-candidate BFO type, or (at low confidence)
# where BFO typing is silent. Word-boundary matched against a normalized label.

LOCUS_CUES = {
    "authority": ("authority", "agency", "board", "ministry", "commission",
                  "organization", "organisation", "council", "college",
                  "association", "bureau", "regulator", "legislature"),
    "criteria": ("criterion", "criteria", "definition", "specification",
                 "requirement", "standard", "guideline", "rule", "condition",
                 "threshold", "code", "provision", "statute", "clause", "norm"),
    "assessor": ("assessor", "examiner", "adjudicator", "clinician",
                 "physician", "officer", "inspector", "judge", "reviewer",
                 "evaluator", "certifier", "auditor", "practitioner",
                 "magistrate", "agent"),
    "facts": ("presentation", "symptom", "sign", "finding", "evidence",
              "observation", "manifestation", "measurement", "complaint",
              "testimony"),
    "act": ("diagnosis", "diagnosing", "determination", "conferral", "grant",
            "granting", "award", "certification", "registration", "ruling",
            "decision", "adjudication", "assessment", "issuance",
            "declaration", "designation", "classification"),
    "effect": ("entitlement", "obligation", "right", "duty", "permission",
               "privilege", "liability", "benefit", "status", "license",
               "licence", "exemption", "reimbursement", "eligibility",
               "immunity", "effect", "consequence", "sanction", "penalty"),
    "remedy": ("appeal", "revocation", "invalidation", "rectification",
               "remedy", "redress", "revision", "correction", "annulment",
               "challenge", "reversal", "vacatur", "rehearing"),
}

_CUE_INDEX = {cue: locus for locus, cues in LOCUS_CUES.items() for cue in cues}
# Word-anchored. Without the boundaries "sign" fires inside "signing" and
# "designation", and a clinical-sign cue silently retypes a signing event.
_CUE_RE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(c) for c in _CUE_INDEX),
                               key=len, reverse=True)) + r")\b")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _local_name(iri):
    return re.split(r"[#/]", iri.rstrip("#/"))[-1]


def normalized_label(iri, label=None):
    """A lower-case, space-separated form of a label or IRI local name."""
    text = label or _local_name(iri)
    text = _CAMEL_RE.sub(" ", text).replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _lexical_loci(text):
    """Every locus whose cues appear in ``text``, in first-match order."""
    out = []
    for match in _CUE_RE.finditer(text):
        locus = _CUE_INDEX[match.group(0)]
        if locus not in out:
            out.append(locus)
    return out


# --- results ------------------------------------------------------------------

@dataclass
class LocusAssignment:
    """One entity placed at one locus, with how we got there."""
    iri: str
    locus: str
    basis: str          # "declared" | "bfo-type" | "bfo-type+label" | "label"
    confidence: str     # "declared" | "high" | "low"
    label: str = ""

    def to_dict(self):
        return {"iri": self.iri, "locus": self.locus, "basis": self.basis,
                "confidence": self.confidence, "label": self.label}


@dataclass
class AmbiguousEntity:
    """An entity whose type admits several loci and whose label settles none."""
    iri: str
    candidates: list
    label: str = ""

    def to_dict(self):
        return {"iri": self.iri, "candidates": self.candidates,
                "label": self.label}


@dataclass
class ChainBinding:
    """The artifact's entities placed along the recognition chain."""
    assignments: dict = field(default_factory=dict)   # iri -> LocusAssignment
    ambiguous: list = field(default_factory=list)     # AmbiguousEntity
    unbound: list = field(default_factory=list)       # iri, no locus at all

    def locus_of(self, iri):
        a = self.assignments.get(iri)
        return a.locus if a else None

    def entities_at(self, locus):
        return [iri for iri, a in self.assignments.items() if a.locus == locus]

    @property
    def occupied_loci(self):
        """Locus keys with at least one entity, in chain order."""
        present = {a.locus for a in self.assignments.values()}
        return [k for k in LOCUS_KEYS if k in present]

    @property
    def is_declared(self):
        """True when any assignment came from an annotation or override.

        A wholly proposed binding is a hypothesis about the artifact, and the
        report says so.
        """
        return any(a.confidence == "declared" for a in self.assignments.values())

    def to_dict(self):
        return {
            "declared": self.is_declared,
            "occupied_loci": self.occupied_loci,
            "counts": {k: len(self.entities_at(k)) for k in LOCUS_KEYS},
            "assignments": [a.to_dict() for a in self.assignments.values()],
            "ambiguous": [a.to_dict() for a in self.ambiguous],
            "unbound_count": len(self.unbound),
        }


# --- declared bindings --------------------------------------------------------

def _locus_from_value(value):
    """Normalize an annotation value to a locus key, or None."""
    text = str(value).strip()
    if text.startswith(RECOG_NS):
        text = text[len(RECOG_NS):]
    text = _local_name(text) if ("#" in text or "/" in text) else text
    text = text.replace("-", "_").replace(" ", "_").lower()
    aliases = {"assessor_in_role": "assessor", "presenting_facts": "facts",
               "recognition_act": "act", "criterion": "criteria"}
    text = aliases.get(text, text)
    return text if text in LOCUS_KEYS else None


def declared_bindings(graph):
    """Locus assignments declared by annotation in the artifact itself."""
    out = {}
    if graph is None:
        return out
    try:
        from rdflib import URIRef
    except Exception:  # noqa: BLE001 - rdflib absent; nothing to read
        return out
    for s, p, o in graph:
        if not isinstance(s, URIRef):
            continue
        if _local_name(str(p)) not in _LOCUS_PREDICATES:
            continue
        locus = _locus_from_value(o)
        if locus:
            out[str(s)] = locus
    return out


def _labels(graph):
    """rdfs:label per subject, first one wins."""
    out = {}
    if graph is None:
        return out
    try:
        from rdflib import RDFS, URIRef
    except Exception:  # noqa: BLE001
        return out
    for s, _p, o in graph.triples((None, RDFS.label, None)):
        if isinstance(s, URIRef) and str(s) not in out:
            out[str(s)] = str(o)
    return out


# --- the proposer -------------------------------------------------------------

def _upper_anchors(ctx, cls_iri):
    """Upper-ontology ancestors of ``cls_iri``, BFO *and* IAO.

    ``GateContext.bfo_parents`` stops at the BFO namespace, so a class grounded
    through ``IAO:directive information entity`` looks unanchored to it. The
    criteria locus is exactly where IAO does the work, so we walk the same
    subClassOf edges with a wider prefix set.
    """
    anchors, seen = set(), set()
    stack = list(ctx.edges.get(cls_iri, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if node.startswith(UPPER_PREFIXES):
            anchors.add(node)
            continue          # do not walk up through the upper ontology itself
        stack.extend(ctx.edges.get(node, ()))
    return anchors


def _type_closure(anchors, catalog):
    """``anchors`` plus their BFO ancestors, as a set of IRIs."""
    closure = set(anchors)
    if catalog is not None:
        for anchor in anchors:
            try:
                closure.update(catalog.ancestors(anchor))
            except Exception:  # noqa: BLE001 - catalog is best-effort
                pass
    return closure


def _type_candidates(closure):
    """Loci the entity's upper type is compatible with, most specific first."""
    for type_iri, loci in BFO_TYPE_LOCI:
        if type_iri in closure:
            return list(loci)
    return []


def propose(ctx, overrides=None):
    """Build a ChainBinding for ``ctx`` (an owltester GateContext).

    ``overrides`` is an optional ``{iri: locus}`` mapping from the user; it
    carries the same authority as an in-artifact annotation.
    """
    binding = ChainBinding()
    labels = _labels(ctx.graph)
    declared = declared_bindings(ctx.graph)
    for iri, locus in (overrides or {}).items():
        resolved = _locus_from_value(locus)
        if resolved:
            declared[iri] = resolved

    for iri in ctx.classes:
        label = labels.get(iri, "")
        text = normalized_label(iri, label)

        if iri in declared:
            binding.assignments[iri] = LocusAssignment(
                iri, declared[iri], "declared", "declared", label)
            continue

        closure = _type_closure(_upper_anchors(ctx, iri), ctx.catalog)
        candidates = _type_candidates(closure)
        lexical = _lexical_loci(text)

        agreed = [locus for locus in lexical if locus in candidates]

        if not lexical:
            # No label cue, so nothing places this entity on a chain. This is
            # the branch that keeps scientific ontologies out of the
            # institutional rows: a depolarization stays a depolarization.
            binding.unbound.append(iri)
        elif len(agreed) == 1:
            # Label and upper type converge. "Board examiner" names both the
            # authority and the assessor loci on cues alone; BFO role admits
            # only one of them, and that settles it.
            binding.assignments[iri] = LocusAssignment(
                iri, agreed[0], "bfo-type+label", "high", label)
        elif len(agreed) > 1:
            # The type corroborates several of the label's loci, so neither
            # source settles it.
            binding.ambiguous.append(AmbiguousEntity(iri, agreed, label))
        elif len(lexical) > 1:
            # Several cues, none corroborated by the type. "Sign contract
            # obligation" is a fact and an effect on its own evidence; picking
            # the first would be a coin toss wearing a confidence score.
            binding.ambiguous.append(AmbiguousEntity(iri, lexical, label))
        elif not candidates:
            # A single cue, but no upper typing to corroborate it.
            binding.assignments[iri] = LocusAssignment(
                iri, lexical[0], "label", "low", label)
        else:
            # A single cue the upper type contradicts. Worth surfacing: a class
            # labelled "diagnostic criterion" but grounded as a material entity
            # is either mislabelled or misgrounded, and either way the locus
            # rests on the label alone.
            binding.assignments[iri] = LocusAssignment(
                iri, lexical[0], "label-over-type", "low", label)

    return binding
