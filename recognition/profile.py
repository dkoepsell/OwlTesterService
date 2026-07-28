"""The stratum profile as an institutional fingerprint (paper §6.4).

The empty cells are as informative as the filled ones. Strata A through C apply
to any ontology whatsoever — a gene ontology, a chemical nomenclature, or an
anatomical atlas can all suffer inconsistency, circularity, or category
violation. Stratum D fires only where there are acts. That gives a principled
account of what distinguishes an institutional ontology from a scientific one:
institutional ontologies are exactly those capable of pragmatic contradiction.

Two things this module is careful about.

**Artifact versus object.** What the file *is* and what the file is *about* can
sit in different rows. The Mental Functioning and Mental Disease Ontologies are
scientific reference ontologies and, as artifacts, occupy row one correctly and
by design; their object, a psychiatric classification in use, occupies row two.
Applying a row-one instrument to a row-two object is not an error of execution,
it is a mismatch of stratum profile — and, as the paper stresses, it is
detectable before any content is examined. We can read the artifact's row off
its chain occupancy; the object's row has to be declared, so we ask for it and
report the mismatch when the two disagree.

**Expected versus observed.** An empty Stratum D on an act-thin artifact is not
missing data, it is the correct result. An empty Stratum D that merely reflects
an instrument we never ran is missing data. The fingerprint keeps those apart.
"""

from dataclasses import dataclass, field

from .kernel import STRATA, SYSTEM_CLASSES, system_class


def chain_thickness(binding):
    """How much of the recognition chain the artifact actually models."""
    occupied = set(binding.occupied_loci)
    return {
        "occupied": [k for k in ("authority", "criteria", "assessor", "facts",
                                 "act", "effect", "remedy") if k in occupied],
        "has_authority": "authority" in occupied,
        "has_criteria": "criteria" in occupied,
        "act_thick": "act" in occupied,
        "repair_thick": "remedy" in occupied,
    }


def classify(binding):
    """The artifact's system class, from chain occupancy alone.

    Returns ``(key, reasons)``. The rule follows Table 8 directly: no chain at
    all is row one; a chain without acts or remedy is row two; acts *and* remedy
    is row three, the only class in which all twelve primitives can fire.
    """
    t = chain_thickness(binding)
    reasons = []

    institutional = t["has_authority"] or t["has_criteria"]
    if not institutional and not t["act_thick"]:
        reasons.append("No recognition-chain loci are occupied: the artifact "
                       "models no authority, criteria, or conferring act.")
        return "scientific", reasons

    if t["act_thick"] and t["repair_thick"]:
        reasons.append("Both a recognition act and a remedy locus are occupied: "
                       "the artifact models conferral and its correction.")
        return "act-thick", reasons

    if t["act_thick"]:
        reasons.append("A recognition act is modelled but no remedy locus is "
                       "occupied: repair is external to the artifact.")
    else:
        reasons.append("Criteria or authority are modelled but no conferring "
                       "act is: assessment is external to the artifact.")
    return "recognition-only", reasons


def expected_strata(system_key):
    """Strata that *can* fire for a system class, as bare letters.

    Table 8 writes row two's fourth stratum as "D(thin)": a recognition-only
    institution has acts, but they happen outside the artifact. Thin still
    counts as possible, so the qualifier is dropped here and carried in the
    system class's own record.
    """
    spec = system_class(system_key)
    if not spec:
        return ["A", "B", "C"]
    return [s.split("(", 1)[0] for s in spec["active_strata"]]


@dataclass
class Fingerprint:
    """The pre-content verdict: what kind of institutional object is this?"""
    artifact_class: str                     # SYSTEM_CLASSES key
    reasons: list = field(default_factory=list)
    thickness: dict = field(default_factory=dict)
    declared_object_class: str = ""
    warnings: list = field(default_factory=list)
    strata: dict = field(default_factory=dict)   # letter -> status record

    @property
    def mismatch(self):
        return bool(self.declared_object_class
                    and self.declared_object_class != self.artifact_class)

    def to_dict(self):
        spec = system_class(self.artifact_class) or {}
        return {
            "artifact_class": self.artifact_class,
            "artifact_class_name": spec.get("name", self.artifact_class),
            "chain_thickness": spec.get("chain_thickness", ""),
            "character": spec.get("character", ""),
            "reasons": self.reasons,
            "thickness": self.thickness,
            "declared_object_class": self.declared_object_class,
            "stratum_mismatch": self.mismatch,
            "warnings": self.warnings,
            "strata": self.strata,
        }


def _stratum_status(letter, expected, attempted, observed_counts):
    """One row of the stratum table: expected, assessed, and what was found.

    The three-way distinction is the whole point. ``not-applicable`` means the
    stratum cannot fire for this kind of artifact and an empty cell is correct.
    ``not-assessed`` means nothing that could see it ever ran, and an empty
    cell means nothing at all. Only ``assessed`` licenses reading a zero as a
    zero.

    Coverage is tracked per *primitive*, not per instrument. A machine with no
    Java gets K-C1 from structural lint but no reasoner verdict on K-A1 or
    K-A2, and calling that "the DL instrument ran" would report two thirds of
    Stratum A as clean on the strength of a check that never happened.
    """
    from .kernel import KERNEL

    primitives = [k["id"] for k in KERNEL if k["stratum"] == letter]
    covered = [p for p in primitives if p in attempted]

    if letter not in expected:
        status = "not-applicable"
    elif not covered:
        status = "not-assessed"
    elif len(covered) < len(primitives):
        status = "partially-assessed"
    else:
        status = "assessed"

    row = {
        "stratum": letter,
        "status": status,
        "primitives": primitives,
        "primitives_assessed": covered,
        "primitives_unassessed": [p for p in primitives if p not in attempted],
        "findings": observed_counts.get(letter, 0) if observed_counts else 0,
    }
    if status == "not-applicable":
        row["reading"] = ("Cannot fire for this kind of artifact; an empty "
                          "cell here is the correct result.")
    elif status in ("not-assessed", "partially-assessed"):
        row["reading"] = ("No flag here is not evidence of no failure: "
                          + ", ".join(row["primitives_unassessed"])
                          + " were never looked for.")
    return row


def build(binding, primitives_attempted=None, available_instruments=None,
          declared_object_class="", observed_counts=None):
    """The fingerprint for an artifact.

    ``primitives_attempted`` is the set of kernel ids some detector actually
    looked for. ``available_instruments`` is a coarser shorthand -- a tuple of
    detectability classes from kernel.INSTRUMENTS -- expanded to the primitives
    those instruments can see; pass it only when per-primitive coverage is not
    available. ``declared_object_class`` is the user's statement about what the
    ontology is *about*, which the artifact cannot supply. ``observed_counts``
    maps stratum letter to finding count; omit it for the pre-content pass.
    """
    from .kernel import primitives_for

    if primitives_attempted is None:
        instruments = ("dl", "structural") if available_instruments is None \
            else available_instruments
        primitives_attempted = {p for i in instruments for p in primitives_for(i)}
    attempted = set(primitives_attempted)

    artifact_class, reasons = classify(binding)
    t = chain_thickness(binding)
    expected = expected_strata(artifact_class)

    fp = Fingerprint(artifact_class=artifact_class, reasons=reasons,
                     thickness=t,
                     declared_object_class=declared_object_class or "")

    fp.strata = {s["key"]: _stratum_status(s["key"], expected, attempted,
                                           observed_counts or {})
                 for s in STRATA}

    if not binding.is_declared and binding.assignments:
        fp.warnings.append(
            "The chain binding is proposed from BFO typing and labels, not "
            "declared. Every locus-indexed figure below inherits that "
            "uncertainty; declare the binding to remove it.")
    if binding.ambiguous:
        fp.warnings.append(
            f"{len(binding.ambiguous)} entities have a BFO type admitting more "
            "than one chain locus and no label that settles it. They are left "
            "unassigned rather than guessed.")

    if fp.mismatch:
        artifact_name = (system_class(artifact_class) or {}).get("name", artifact_class)
        object_name = (system_class(fp.declared_object_class) or {}).get(
            "name", fp.declared_object_class)
        fp.warnings.append(
            f"Stratum-profile mismatch: this artifact is a {artifact_name.lower()}, "
            f"but its declared object is a {object_name.lower()}. Assessing the "
            "object with an instrument shaped for the artifact is not an error "
            "of execution, it is a mismatch of profile, and everything the "
            "object's own acts and remedies could contribute is out of reach.")

    unassessed = [k for k, v in fp.strata.items()
                  if v["status"] in ("not-assessed", "partially-assessed")]
    if unassessed:
        fp.warnings.append(
            "Strata " + ", ".join(unassessed) + " were not fully assessed. A "
            "reasoner is necessary and never sufficient: half the kernel is "
            "invisible to description logic in principle.")

    return fp


def system_class_options():
    """The three rows of Table 8, for a UI that asks the user to declare one."""
    return [{"key": s["key"], "name": s["name"], "examples": s["examples"],
             "chain_thickness": s["chain_thickness"],
             "character": s["character"]} for s in SYSTEM_CLASSES]
