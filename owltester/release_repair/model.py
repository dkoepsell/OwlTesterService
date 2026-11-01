"""The remedy model (spec section 3.2)."""

from dataclasses import MISSING, asdict, dataclass, field

KINDS = ("mechanical", "choice", "guided", "declare")
STATUSES = ("open", "accepted", "skipped", "declared", "applied", "reverted")
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}


@dataclass
class RemedyOption:
    id: str                       # "a", "b", ...
    label: str
    consequence: str              # what changes, and what it costs
    ops: list = field(default_factory=list)       # list[dict] (ops.OP_NAMES)
    preview: dict = field(default_factory=dict)   # counts per file, samples, Turtle
    recommended: bool = False
    # Guided options take content from the user. ``input`` describes the slot:
    # {"kind": "turtle"|"text"|"iri"|"table", "label": ..., "default": ..., "rows": [...]}
    input: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k, v) for k, v in _defaults(cls).items()})


@dataclass
class Remedy:
    id: str                       # "M-<finding id>"
    finding_id: str
    code: str
    kind: str                     # mechanical | choice | guided | declare
    title: str
    rationale: str
    options: list = field(default_factory=list)   # list[RemedyOption]
    depends_on: list = field(default_factory=list)
    status: str = "open"
    decision: dict = None         # {option, by, at, note, ai_assisted, content}
    severity: str = "info"
    files: list = field(default_factory=list)
    explanation: str = ""         # longer guidance for guided cards
    comments: list = field(default_factory=list)  # reviewers' comments and proposals

    def option(self, oid):
        return next((o for o in self.options if o.id == oid), None)

    def to_dict(self):
        d = asdict(self)
        d["options"] = [asdict(o) for o in self.options]
        return d

    @classmethod
    def from_dict(cls, d):
        r = cls(**{k: d.get(k, v) for k, v in _defaults(cls).items()})
        r.options = [RemedyOption.from_dict(o) for o in d.get("options", [])]
        return r


def _defaults(cls):
    """Field name -> default value (None for required fields)."""
    out = {}
    for name, f in cls.__dataclass_fields__.items():
        if f.default_factory is not MISSING:
            out[name] = f.default_factory()
        else:
            out[name] = None if f.default is MISSING else f.default
    return out


@dataclass
class Plan:
    plan_id: str
    job_id: str
    artifact: str
    profile: str
    created_at: str
    created_by: dict              # {user_id, name}
    remedies: list = field(default_factory=list)  # list[Remedy]
    members: list = field(default_factory=list)   # [{user_id, name, role, added_by, added_at}]
    release_sha256: str = ""
    audit_before: dict = field(default_factory=dict)
    apply: dict = field(default_factory=dict)     # {status, started_at, finished_at, error, result}
    log: list = field(default_factory=list)       # plan-level events (who decided what)
    prefixes: list = field(default_factory=list)  # [[prefix, namespace]] for drafts
    status: str = "ready"         # building | ready | error
    error: str = ""
    owned: list = field(default_factory=list)     # the release's own namespaces
    build: dict = field(default_factory=dict)     # while building: {stage, done, total, updated_at}

    def remedy(self, rid):
        return next((r for r in self.remedies if r.id == rid), None)

    def progress(self):
        decided = sum(1 for r in self.remedies if r.status != "open")
        return {"decided": decided, "total": len(self.remedies)}

    def to_dict(self):
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["remedies"] = [r.to_dict() for r in self.remedies]
        return d

    @classmethod
    def from_dict(cls, d):
        p = cls(**{k: d.get(k, v) for k, v in _defaults(cls).items()})
        p.remedies = [Remedy.from_dict(r) for r in d.get("remedies", [])]
        return p
