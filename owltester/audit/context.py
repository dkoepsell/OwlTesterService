"""Shared state for one audit run: budgets, findings, stage results.

Stages never halt the audit. Each records findings through ``AuditContext.add``
and a status through ``AuditContext.finish``; a budget that runs out is listed
under ``limits_hit`` rather than raised.
"""

import threading
import time

from ..model import AuditFinding

DEFAULT_BUDGETS = {
    "total": 900,           # whole audit, seconds
    "reasoner": 60,         # one reasoner call
    "explain": 120,         # explanation search per inconsistent file
    "max_explanations": 3,  # inconsistent files explained
    "shacl": 60,            # SHACL validation of one file
}


class Budget:
    def __init__(self, **overrides):
        self.limits = dict(DEFAULT_BUDGETS)
        self.limits.update({k: v for k, v in overrides.items() if v is not None})
        self.started = time.monotonic()

    def __getitem__(self, key):
        return self.limits[key]

    def elapsed(self):
        return time.monotonic() - self.started

    def remaining(self):
        return max(0.0, self.limits["total"] - self.elapsed())

    def expired(self):
        return self.remaining() <= 0

    def cap(self, key):
        """A per-call budget, never longer than what is left of the total."""
        return max(0.001, min(self.limits[key], self.remaining()))


class TimedOut(Exception):
    pass


def run_with_timeout(fn, seconds, *args, **kwargs):
    """Run ``fn`` in a daemon thread; raise TimedOut if it does not finish.

    The thread is abandoned on timeout (pySHACL cannot be interrupted), which is
    acceptable for a worker that is about to move on to the next file."""
    box = {}

    def go():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimedOut(f"did not finish within {seconds:g} seconds")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class AuditContext:
    def __init__(self, artifact, profile, budget=None, options=None, progress=None):
        self.artifact = artifact
        self.profile = profile
        self.budget = budget or Budget()
        self.options = options or {}
        self.progress = progress or (lambda stage, note="": None)
        self.findings = []
        self.stages = {}
        self.patches = []
        self.limits_hit = []
        self.cache = {}
        self._counter = {}

    # -- findings -------------------------------------------------------------

    def add(self, stage, code, severity, title, message="", *, files=(), count=1,
            evidence=None, iri="", fix="", related=(), suggested_rewrite=""):
        severity = self.profile.get("severity_overrides", {}).get(code, severity)
        n = self._counter.get(stage, 0) + 1
        self._counter[stage] = n
        f = AuditFinding(code=code, message=message or title, iri=iri,
                         suggested_rewrite=suggested_rewrite, stage=stage,
                         severity=severity, title=title, files=sorted(set(files)),
                         count=count, evidence=evidence or {}, related=list(related),
                         fix=fix, id=f"{stage}-{n}")
        self.findings.append(f)
        return f

    def stage_findings(self, stage):
        return [f for f in self.findings if f.stage == stage]

    def finish(self, stage, title, status=None, summary="", notes=None):
        """Record a stage result; status defaults from the stage's findings."""
        if status is None:
            sev = {f.severity for f in self.stage_findings(stage)}
            status = "fail" if sev & {"critical", "major"} else "warn" if "minor" in sev else "pass"
        self.stages[stage] = {"title": title, "status": status, "summary": summary,
                              "notes": notes or {}}

    def skip(self, stage, title, reason):
        self.stages[stage] = {"title": title, "status": "skipped", "summary": reason,
                              "notes": {}}

    def limit(self, stage, what, detail=""):
        self.limits_hit.append({"stage": stage, "limit": what, "detail": detail})
