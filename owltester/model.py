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


# -- full artifact audit (SPEC-audit.md, section 3) ---------------------------------

SEVERITIES = ("critical", "major", "minor", "info")
STAGE_ORDER = ("R0", "R1", "R2", "R2b", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")


def _rank(seq, item):
    return seq.index(item) if item in seq else len(seq)


@dataclass
class AuditFinding(Finding):
    """One folded audit finding: a code with a count, a few examples and a fix,
    never one finding per triple."""
    stage: str = ""
    severity: str = "info"
    title: str = ""
    files: list = field(default_factory=list)
    count: int = 1
    evidence: dict = field(default_factory=dict)
    related: list = field(default_factory=list)
    fix: str = ""
    id: str = ""
    expected: str = ""      # reason, when the release declares this outcome expected

    def to_dict(self):
        d = super().to_dict()
        d.update({"id": self.id, "stage": self.stage, "severity": self.severity,
                  "title": self.title, "files": list(self.files), "count": self.count,
                  "evidence": self.evidence, "related": list(self.related), "fix": self.fix})
        if self.expected:
            d["expected"] = self.expected
        return d

    @classmethod
    def from_dict(cls, d):
        keys = ("code", "message", "iri", "suggested_rewrite", "stage", "severity", "title",
                "files", "count", "evidence", "related", "fix", "id", "expected")
        return cls(**{k: d[k] for k in keys if k in d})


@dataclass
class AuditReport:
    artifact: str
    audited_at: str
    tool_version: str
    profile: str
    manifest: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)      # "R1" -> {title, status, summary, notes}
    findings: list = field(default_factory=list)    # list[AuditFinding]
    patches: list = field(default_factory=list)
    limits_hit: list = field(default_factory=list)
    lenses: list = field(default_factory=list)      # section 9 coverage tables

    def sorted_findings(self):
        return sorted(self.findings, key=lambda f: (
            _rank(SEVERITIES, f.severity), _rank(STAGE_ORDER, f.stage), f.id))

    @property
    def verdict(self):
        """"fail" if any critical, "warn" if any major, else "pass". Findings the
        release declares expected (audit config ``expected``) do not count."""
        sev = {f.severity for f in self.findings if not f.expected}
        if "critical" in sev:
            return "fail"
        if "major" in sev:
            return "warn"
        return "pass"

    def severity_counts(self):
        out = {s: 0 for s in SEVERITIES}
        for f in self.findings:
            if not f.expected:
                out[f.severity] = out.get(f.severity, 0) + 1
        expected = sum(1 for f in self.findings if f.expected)
        if expected:
            out["expected"] = expected
        return out

    def scorecard(self):
        """One row per check, as in the LOMO audit document."""
        rows = []
        for stage in STAGE_ORDER:
            st = self.stages.get(stage)
            if st is None:
                continue
            mine = [f for f in self.findings if f.stage == stage]
            worst = next((s for s in SEVERITIES
                          if any(f.severity == s and not f.expected for f in mine)), "")
            rows.append({"stage": stage, "check": st.get("title", stage),
                         "status": st.get("status", ""), "worst": worst,
                         "findings": len(mine), "summary": st.get("summary", "")})
        return rows

    def to_dict(self):
        return {
            "artifact": self.artifact,
            "audited_at": self.audited_at,
            "tool_version": self.tool_version,
            "profile": self.profile,
            "verdict": self.verdict,
            "severity_counts": self.severity_counts(),
            "scorecard": self.scorecard(),
            "manifest": self.manifest,
            "stages": self.stages,
            "findings": [f.to_dict() for f in self.sorted_findings()],
            "patches": self.patches,
            "limits_hit": self.limits_hit,
            "lenses": self.lenses,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(artifact=d["artifact"], audited_at=d["audited_at"],
                   tool_version=d["tool_version"], profile=d["profile"],
                   manifest=d.get("manifest", {}), stages=d.get("stages", {}),
                   findings=[AuditFinding.from_dict(f) for f in d.get("findings", [])],
                   patches=d.get("patches", []), limits_hit=d.get("limits_hit", []),
                   lenses=d.get("lenses", []))
