"""Pragmatic contradiction: the stratum that fires only where there are acts.

    K-D1  falsification            world-facing evidence contradicts the artifact
    K-D2  performative self-defeat the act undermines its own preconditions
    K-D3  modal clash              structure permits, practice forecloses

None of these is recoverable from an OWL file, and no amount of better tooling
will change that. Table 7 assigns K-D1 to world-facing data and K-D2/K-D3 to
process-level modelling; an artifact contains neither. This is the concrete
sense in which "a reasoner is necessary and never sufficient".

So the input is a declared **institutional record** supplied alongside the
ontology. Where none is supplied, every D primitive is reported unattempted and
the fingerprint says so. The alternative -- returning zero findings -- would
score three of twelve primitives clean on the strength of never having looked,
which is the reporting failure the paper's own audit lists against itself
("absence of a flag is not evidence of absence of the failure").

Record shape::

    {
      "adjudications": [
        {"category": "<iri or label>", "outcome": "contradicted|upheld",
         "source": "<citation>"}
      ],
      "acts": [
        {"act": "<iri or label>",
         "preconditions": ["<token>", ...],
         "effects": ["<token>", "!<token>", ...]}
      ],
      "modal_pairs": [
        {"possibility": "<description>",
         "possible_in_structure": true, "possible_in_practice": false}
      ]
    }

An effect written ``"!x"`` negates ``x``. Where an act's effects negate one of
its own preconditions, the act undermines the conditions of its own success.
"""

from ..finding import DetectorResult, RecognitionFinding

INSTRUMENT_WORLD = "world"
INSTRUMENT_PROCESS = "process"

PRIMITIVES = {"K-D1", "K-D2", "K-D3"}

CONTRADICTED = "contradicted"


class RecordError(ValueError):
    """The supplied institutional record is not usable."""


def validate(record):
    """Check a record's shape, returning ``(record, warnings)``.

    Raises RecordError on anything structurally unusable. Unknown keys are
    warned about rather than rejected, so a record carrying extra provenance
    still works.
    """
    if record is None:
        return None, []
    if not isinstance(record, dict):
        raise RecordError("institutional record must be an object")

    warnings = []
    known = {"adjudications", "acts", "modal_pairs"}
    for key in record:
        if key not in known:
            warnings.append(f"ignoring unknown key in record: {key}")

    for key in known:
        value = record.get(key, [])
        if not isinstance(value, list):
            raise RecordError(f"record field '{key}' must be a list")
        for i, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise RecordError(f"{key}[{i}] must be an object")

    for i, adj in enumerate(record.get("adjudications", [])):
        if not adj.get("category"):
            raise RecordError(f"adjudications[{i}] needs a 'category'")
        if adj.get("outcome") not in ("contradicted", "upheld", None):
            warnings.append(
                f"adjudications[{i}] has an unrecognised outcome "
                f"{adj.get('outcome')!r}; only 'contradicted' fires K-D1")

    for i, act in enumerate(record.get("acts", [])):
        if not act.get("act"):
            raise RecordError(f"acts[{i}] needs an 'act'")
        for field in ("preconditions", "effects"):
            if not isinstance(act.get(field, []), list):
                raise RecordError(f"acts[{i}].{field} must be a list")

    for i, pair in enumerate(record.get("modal_pairs", [])):
        if not pair.get("possibility"):
            raise RecordError(f"modal_pairs[{i}] needs a 'possibility'")

    return record, warnings


def _normalize(token):
    return str(token).strip().lower()


def _negated(token):
    """``("x", True)`` for ``"!x"`` / ``"not x"``, else ``("x", False)``."""
    text = str(token).strip()
    if text.startswith("!"):
        return _normalize(text[1:]), True
    lowered = text.lower()
    for prefix in ("not ", "no "):
        if lowered.startswith(prefix):
            return _normalize(text[len(prefix):]), True
    return _normalize(text), False


# --- K-D1 ---------------------------------------------------------------------

def falsifications(record, binding=None):
    """K-D1. Evidence from the world contradicts a conferred classification.

    The artifact stays internally coherent throughout -- that is what makes
    this a distinct primitive rather than a variant of K-A1. Only adjudicated
    or audited outcomes count; a disagreement is not a falsification.
    """
    findings = []
    for adj in record.get("adjudications", []):
        if adj.get("outcome") != CONTRADICTED:
            continue
        category = adj["category"]
        findings.append(RecognitionFinding(
            kernel="K-D1",
            message=("Adjudicated evidence contradicts the classification of "
                     f"{category}"),
            iri=category if category.startswith("http") else "",
            locus=_locus(binding, category) or "act",
            instrument=INSTRUMENT_WORLD,
            evidence={"category": category,
                      "source": adj.get("source", ""),
                      "note": "The artifact may be internally coherent "
                              "throughout; this is a failure against the "
                              "world, not against the theory."}))
    return findings


# --- K-D2 ---------------------------------------------------------------------

def self_defeats(record, binding=None):
    """K-D2. An act whose effects negate one of its own preconditions."""
    findings = []
    for act in record.get("acts", []):
        preconditions = {_negated(p)[0] for p in act.get("preconditions", [])}
        defeated = []
        for effect in act.get("effects", []):
            token, negated = _negated(effect)
            if negated and token in preconditions:
                defeated.append(token)
        if not defeated:
            continue
        name = act["act"]
        findings.append(RecognitionFinding(
            kernel="K-D2",
            message=(f"The act {name} undermines the conditions of its own "
                     "success: it negates " + ", ".join(sorted(defeated))),
            iri=name if name.startswith("http") else "",
            locus=_locus(binding, name) or "act",
            instrument=INSTRUMENT_PROCESS,
            evidence={"act": name, "defeated_preconditions": sorted(defeated)}))
    return findings


# --- K-D3 ---------------------------------------------------------------------

def modal_clashes(record, binding=None):
    """K-D3. What the institution's structure permits, its practice forecloses.

    The remedy locus is where this usually bites: an appeal route that formally
    exists and is in practice unavailable is a repair-thick institution behaving
    as a repair-external one.
    """
    findings = []
    for pair in record.get("modal_pairs", []):
        if not (pair.get("possible_in_structure")
                and pair.get("possible_in_practice") is False):
            continue
        possibility = pair["possibility"]
        findings.append(RecognitionFinding(
            kernel="K-D3",
            message=(f"Structure permits {possibility} but practice forecloses "
                     "it"),
            locus=pair.get("locus") or "remedy",
            instrument=INSTRUMENT_PROCESS,
            evidence={"possibility": possibility,
                      "note": pair.get("note", "")}))
    return findings


def _locus(binding, iri):
    if not binding or not str(iri).startswith("http"):
        return ""
    return binding.locus_of(iri) or ""


# --- entry point --------------------------------------------------------------

def run(record, binding=None):
    """Stratum D from a declared institutional record.

    With no record, nothing is attempted -- deliberately. Returning an empty
    finding list *and* an empty attempted set is what keeps the fingerprint
    reporting D as unassessed rather than clean.
    """
    result = DetectorResult()
    if record is None:
        result.notes["K-D1/K-D2/K-D3"] = (
            "no institutional record supplied; Stratum D cannot be assessed "
            "from an artifact alone")
        return result

    record, warnings = validate(record)
    if warnings:
        result.notes["record_warnings"] = warnings

    # Each primitive is attempted only if the record actually carries the kind
    # of evidence it needs. A record listing adjudications says nothing about
    # whether anyone modelled the acts, so it must not buy coverage of K-D2.
    for key, primitive, detector in (
            ("adjudications", "K-D1", falsifications),
            ("acts", "K-D2", self_defeats),
            ("modal_pairs", "K-D3", modal_clashes)):
        if key not in record:
            result.notes[primitive] = f"record carries no '{key}'"
            continue
        result.findings.extend(detector(record, binding))
        result.attempted.add(primitive)

    return result
