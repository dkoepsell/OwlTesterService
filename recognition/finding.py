"""A defect typed by the kernel and indexed to a chain locus.

Distinct from ``owltester.model.Finding``, which records a gate conformance
failure. A RecognitionFinding answers a different question: not "did this
artifact pass" but "which kernel primitive fired, where on the recognition
chain, and can we tell whether the defect belongs to the classification or to
our translation of it".

That last field is not decoration. The paper's own audit (§10) reports that the
largest single source of incoherence in its pipeline was a defect in the
*extractor*, not in any source text, and that its reporting layer once
described translation errors as errors in the source. Attribution defaults to
``undetermined`` precisely so that nobody can read an unattributed finding as an
accusation against the source.
"""

from dataclasses import dataclass, field

from .kernel import classificatory_type, primitive, stratum_of

# Who the defect belongs to (§10).
ARTIFACT = "artifact"          # our translation introduced it
SOURCE = "source"              # the classification itself has it
UNDETERMINED = "undetermined"  # not established either way -- the default

# Whether a flag is a per-entity discovery or a blanket modelling decision
# propagated from a parent (§9.3). Conflating the two is what let a headline
# density figure of 1.123 stand until it was corrected to 0.129.
PER_ENTITY = "per-entity"
BLANKET = "blanket"


@dataclass
class DetectorResult:
    """What a detector found, and what it actually looked for.

    The second half is the load-bearing one. "Looked for K-A2 and found none"
    and "never looked for K-A2" are different facts about an artifact, and only
    the first licenses reading an empty stratum as clean. Detectors therefore
    declare their attempted primitives rather than letting the report infer
    coverage from which module happened to be imported.
    """
    findings: list = field(default_factory=list)
    attempted: set = field(default_factory=set)
    notes: dict = field(default_factory=dict)

    def extend(self, other):
        self.findings.extend(other.findings)
        self.attempted |= other.attempted
        self.notes.update(other.notes)
        return self


@dataclass
class RecognitionFinding:
    kernel: str                       # "K-A1" ... "K-D3"
    message: str
    iri: str = ""
    locus: str = ""                   # chain locus key, "" if unbound
    instrument: str = ""              # which detectability class saw it
    attribution: str = UNDETERMINED
    flag_scope: str = PER_ENTITY
    evidence: dict = field(default_factory=dict)

    @property
    def stratum(self):
        return stratum_of(self.kernel)

    @property
    def classificatory_type(self):
        """The CT-n record this finding instantiates, if the pair names one."""
        return classificatory_type(self.kernel, self.locus or None)

    @property
    def counts_toward_debt(self):
        """Whether this finding enters the corrected contradiction debt.

        Two exclusions, both from the paper's audit. A defect we introduced in
        translation is not a defect of the classification (§10.1). A blanket
        flag is a modelling decision recorded by the builder, not a per-class
        discovery (§9.3).
        """
        return self.attribution != ARTIFACT and self.flag_scope != BLANKET

    def to_dict(self):
        k = primitive(self.kernel) or {}
        ct = self.classificatory_type
        d = {
            "kernel": self.kernel,
            "kernel_name": k.get("name", ""),
            "stratum": self.stratum,
            "message": self.message,
            "instrument": self.instrument,
            "attribution": self.attribution,
            "flag_scope": self.flag_scope,
            "counts_toward_debt": self.counts_toward_debt,
        }
        if self.iri:
            d["iri"] = self.iri
        if self.locus:
            d["locus"] = self.locus
        if ct:
            d["type"] = ct["id"]
            d["type_name"] = ct["name"]
        if self.evidence:
            d["evidence"] = self.evidence
        return d
