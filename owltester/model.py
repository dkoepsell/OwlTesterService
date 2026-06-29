"""Shared result types for the gate."""

from dataclasses import dataclass, field, asdict

from . import errors


@dataclass
class Finding:
    """A single failure: a code, a human message, and (where relevant) the
    offending IRI and a suggested rewrite so the report is actionable."""
    code: str
    message: str
    iri: str = ""
    suggested_rewrite: str = ""

    def to_dict(self):
        d = {"code": self.code, "message": self.message}
        if self.iri:
            d["iri"] = self.iri
        if self.suggested_rewrite:
            d["suggested_rewrite"] = self.suggested_rewrite
        return d


@dataclass
class StageResult:
    stage: str                       # "A".."E"
    passed: bool = True
    skipped: str = ""                # reason, if the stage did not run
    findings: list = field(default_factory=list)   # list[Finding]
    notes: dict = field(default_factory=dict)      # stage-specific extras

    @property
    def codes(self):
        return [f.code for f in self.findings]

    def add(self, code, message, iri="", suggested_rewrite=""):
        self.passed = False
        self.findings.append(Finding(code, message, iri, suggested_rewrite))

    def to_dict(self):
        if self.skipped:
            return {"skipped": self.skipped}
        d = {"pass": self.passed, "failures": self.codes}
        if self.findings:
            d["details"] = [f.to_dict() for f in self.findings]
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class Report:
    artifact: str
    kernel_version: str
    counts: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)        # "A" -> StageResult.to_dict()
    removals: list = field(default_factory=list)
    suggested_rewrites: dict = field(default_factory=dict)
    antipattern_hits: list = field(default_factory=list)

    @property
    def verdict(self):
        for s in self.stages.values():
            if not s.get("skipped") and s.get("pass") is False:
                return "fail"
        return "pass"

    @property
    def all_failures(self):
        out = []
        for s in self.stages.values():
            out.extend(s.get("failures", []))
        return out

    def to_dict(self):
        return {
            "artifact": self.artifact,
            "kernel_version": self.kernel_version,
            "verdict": self.verdict,
            "counts": self.counts,
            "stages": self.stages,
            "antipattern_hits": self.antipattern_hits,
            "removals": self.removals,
            "suggested_rewrites": self.suggested_rewrites,
        }
