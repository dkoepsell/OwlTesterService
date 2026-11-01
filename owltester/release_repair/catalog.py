"""Remedy catalog (spec section 3.4): one builder per finding code.

A builder reads the finding and the release itself (an ``Artifact``) and returns
a ``Remedy`` whose options carry exact ops and previews, or None when it can
compute nothing useful. This module holds the shared helpers and the
mechanical remedies; ``catalog_choice`` and ``catalog_guided`` add the rest.
"""

import re
from collections import Counter

from rdflib import OWL, RDF, RDFS, XSD, BNode, Literal, URIRef
from rdflib.namespace import DCTERMS

from .model import Remedy, RemedyOption
from .ops import count_refs, duplicate_bnodes, n3, read_format
from .templates import ci_commands
from ..audit.schema_checks import NEUTRAL_CLASSES

BUILDERS = {}
MAX_ROWS = 400


def builder(*codes):
    def wrap(fn):
        for c in codes:
            BUILDERS[c] = fn
        return fn
    return wrap


class Ctx:
    """What a builder may consult: the release, the report, and small caches."""

    def __init__(self, art, report):
        self.art = art
        self.report = report
        self.tbox = art.tbox()
        self._canon = {}
        self.findings = {f["id"]: f for f in report.get("findings", [])}

    # -- names ---------------------------------------------------------------------------
    def expand(self, name):
        name = str(name or "").strip()
        if name.startswith("<") and name.endswith(">"):
            return URIRef(name[1:-1])
        if re.match(r"^[a-z][a-z0-9+.-]*://", name, re.I) or name.startswith("urn:"):
            return URIRef(name)
        if ":" in name:
            prefix, local = name.split(":", 1)
            for g in [self.tbox] + [f.graph for f in self.art.rdf_files() if f.graph is not None]:
                ns = dict(g.namespaces()).get(prefix)
                if ns is not None:
                    return URIRef(str(ns) + local)
        return self._qname_index().get(name)

    def _qname_index(self):
        """Names as the audit wrote them (``schema_checks.qname``) back to IRIs; the
        audit falls back to 'segment/local' when no prefix is bound."""
        if not hasattr(self, "_qindex"):
            from ..audit.schema_checks import qname
            idx, seen = {}, set()
            for g in [self.tbox] + [f.graph for f in self.rdf(("ontology", "vocabulary", "shapes"))]:
                for t in g:
                    for x in t:
                        if isinstance(x, URIRef) and x not in seen:
                            seen.add(x)
                            idx.setdefault(qname(self.tbox, x), x)
            self._qindex = idx
        return self._qindex

    def short(self, iri):
        try:
            return self.tbox.namespace_manager.normalizeUri(URIRef(iri))
        except Exception:  # noqa: BLE001
            return f"<{iri}>"

    def label(self, iri):
        lab = self.tbox.value(URIRef(iri), RDFS.label)
        return str(lab) if lab is not None else self.short(iri)

    # -- files ---------------------------------------------------------------------------
    def rdf(self, roles=None):
        return [f for f in self.art.rdf_files() if f.graph is not None
                and (roles is None or f.role in roles)]

    def writable(self, path):
        f = self.art.get(path)
        return f is not None and read_format(f.abspath) is not None

    def ref_counts(self, old, mode="namespace", roles=None):
        out = {}
        for f in self.rdf(roles):
            n = count_refs(f.graph, old, mode)
            if n:
                out[f.path] = n
        return out

    def files_with(self, t, roles=None):
        return [f.path for f in self.rdf(roles) if t in f.graph]

    def canonical(self, path):
        if path not in self._canon:
            from .ops import canonical_graph
            self._canon[path] = canonical_graph(self.art.get(path).graph)
        return self._canon[path]

    def declaring_file(self, s, p=None, o=None, roles=("ontology", "vocabulary")):
        for f in self.rdf(roles):
            if (s, p, o) in f.graph:
                return f.path
        return None

    def sample_lines(self, path, needle, limit=3):
        f = self.art.get(path)
        try:
            text = f.text(2_000_000)
        except Exception:  # noqa: BLE001
            return []
        return [line.strip()[:200] for line in text.splitlines() if needle in line][:limit]

    def owned_namespaces(self):
        return list(self.art.owned_namespaces)


def turtle(triples, ctx=None):
    """A small Turtle snippet for previews and add_triples."""
    import rdflib
    g = rdflib.Graph()
    for prefix, ns in (ctx.tbox.namespaces() if ctx else ()):
        g.bind(prefix, ns, override=False)
    for t in triples:
        g.add(t)
    text = g.serialize(format="turtle")
    return "\n".join(line for line in text.splitlines() if line.strip()) + "\n"


def remedy(finding, kind, title, rationale, options, explanation=""):
    return Remedy(id=f"M-{finding['id']}", finding_id=finding["id"], code=finding["code"],
                  kind=kind, title=title, rationale=rationale, options=options,
                  severity=finding.get("severity", "info"), files=list(finding.get("files") or []),
                  explanation=explanation)


def letters():
    return iter("abcdefghijklmnopqrstuvwxyz")


# -- mechanical remedies ---------------------------------------------------------------------

@builder("E_NS_MISMATCH")
def ns_mismatch(ctx, f):
    ev = f.get("evidence") or {}
    wrong, right = ev.get("wrong_namespace"), ev.get("declared_namespace")
    if not wrong or not right:
        return None
    to_fix = {p: n for p, n in ctx.ref_counts(wrong).items() if ctx.writable(p)}
    if not to_fix:
        return None
    first = next(iter(to_fix))
    before = ctx.sample_lines(first, wrong)
    opts = [RemedyOption(
        id="a", recommended=True,
        label=f"Rewrite the data to the namespace the vocabulary declares ({right})",
        consequence=(f"{sum(to_fix.values()):,} references in {len(to_fix)} file(s) change from "
                     f"{wrong} to {right}. Nothing is removed. Copies of the data that other "
                     "systems already hold under the old form will not match until they are "
                     "updated too."),
        ops=[{"op": "rewrite_iri", "args": {"from": wrong, "to": right, "mode": "namespace",
                                            "files": sorted(to_fix), "expect": to_fix}}],
        preview={"counts": to_fix, "before": before,
                 "after": [line.replace(wrong, right) for line in before]})]
    declared = {p: n for p, n in ctx.ref_counts(right).items() if ctx.writable(p)}
    if declared:
        opts.append(RemedyOption(
            id="b", label=f"Change the vocabulary instead, so that {wrong} becomes the declared form",
            consequence=(f"{sum(declared.values()):,} references in {len(declared)} file(s), "
                         f"including the declarations, move from {right} to {wrong}. Every "
                         "other release, shape and external user of the current namespace "
                         "breaks, so only choose this if the data is the authority."),
            ops=[{"op": "rewrite_iri", "args": {"from": right, "to": wrong, "mode": "namespace",
                                                "files": sorted(declared), "expect": declared}}],
            preview={"counts": declared}))
    return remedy(f, "mechanical", f"Use one namespace: {right}",
                  "References that use a variant of a declared namespace point at terms that do "
                  "not exist, so shapes and queries that look for the declared terms miss them.",
                  opts)


def _literal_fix(rng, lit, tag):
    if rng == XSD.string and lit.language:
        return Literal(str(lit))
    if rng == RDF.langString and not lit.language and lit.datatype in (None, XSD.string):
        return Literal(str(lit), lang=tag)
    if str(rng).startswith(str(XSD)) and rng != XSD.string and lit.datatype != rng:
        cand = Literal(str(lit), datatype=rng)
        if not getattr(cand, "ill_typed", False):
            return cand
    return None


@builder("W_RANGE")
def wrong_range(ctx, f):
    p = URIRef(f.get("iri") or "")
    rng = ctx.tbox.value(p, RDFS.range)
    if not isinstance(rng, URIRef):
        return None
    datatype_props = set(ctx.tbox.subjects(RDF.type, OWL.DatatypeProperty))
    typed = {s for g in [ctx.tbox] + [x.graph for x in ctx.rdf(("data",))] for s in g.subjects(RDF.type, None)}
    lit_ops, add_ops, counts, left = [], [], Counter(), 0
    for df in ctx.rdf(("data",)):
        if not ctx.writable(df.path):
            continue
        tags = Counter(o.language for o in df.graph.objects() if isinstance(o, Literal) and o.language)
        tag = tags.most_common(1)[0][0] if tags else "en"
        changes, untyped = [], []
        for s, o in df.graph.subject_objects(p):
            if isinstance(o, Literal):
                new = _literal_fix(rng, o, tag)
                if new is not None:
                    changes.append([n3(s), n3(p), n3(o), n3(new)])
                elif rng in (XSD.string, RDF.langString) or str(rng).startswith(str(XSD)):
                    left += 1
            elif isinstance(o, URIRef) and p not in datatype_props and o not in typed \
                    and rng not in NEUTRAL_CLASSES and not str(rng).startswith(str(XSD)):
                untyped.append(o)
        if changes and not any(isinstance(x, BNode) for r in changes for x in r[:2]):
            lit_ops.append({"op": "set_literal", "args": {"file": df.path, "changes": changes[:5000]}})
            counts[df.path] += len(changes)
        if untyped:
            add_ops.append({"op": "add_triples", "args": {
                "file": df.path, "turtle": turtle([(o, RDF.type, rng) for o in sorted(set(untyped))], ctx)}})
            counts[df.path] += len(set(untyped))
    if not lit_ops and not add_ops:
        ev = f.get("evidence") or {}
        return remedy(f, "guided", f"Check the values of {ctx.short(p)} against its range",
                      "The objects are typed with classes outside the declared range, which RDFS "
                      "reasoning silently widens.", [],
                      explanation="Examples:\n" + "\n".join(f"- {e}" for e in ev.get("examples", [])) +
                                  "\n\nEither type the objects with the range class, or widen the "
                                  "range in the ontology if these values are intended.")
    sample = (lit_ops[0]["args"]["changes"][:3] if lit_ops else [])
    parts = []
    if lit_ops:
        parts.append(f"{sum(len(o['args']['changes']) for o in lit_ops)} literal(s) get the tag or "
                     "datatype the range asks for; their text is unchanged")
    if add_ops:
        parts.append(f"untyped objects are typed {ctx.short(rng)} explicitly, which is what RDFS "
                     "already infers silently")
    if left:
        parts.append(f"{left} value(s) cannot be converted and stay as they are")
    opt = RemedyOption(id="a", recommended=True,
                       label=f"Make the values of {ctx.short(p)} fit its range {ctx.short(rng)}",
                       consequence="; ".join(parts) + ".", ops=lit_ops + add_ops,
                       preview={"counts": dict(counts),
                                "before": [r[2] for r in sample], "after": [r[3] for r in sample],
                                "turtle": add_ops[0]["args"]["turtle"][:1500] if add_ops else ""})
    return remedy(f, "mechanical", f"Fit the values of {ctx.short(p)} to its range",
                  "Values that do not fit the declared range are either rejected by strict "
                  "tools or silently retyped by RDFS reasoning.", [opt])


@builder("W_DUPLICATE_NODE")
def duplicate_nodes(ctx, f):
    ds = (f.get("evidence") or {}).get("data_set")
    files = [x for x in ctx.rdf(("data",)) if (ds is None or x.data_set == ds) and ctx.writable(x.path)]
    counts = {}
    for x in files:
        n = sum(len(d[2]) for d in duplicate_bnodes(x.graph))
        if n:
            counts[x.path] = n
    if not counts:
        return None
    opt = RemedyOption(id="a", recommended=True, label="Collapse the identical blank nodes",
                       consequence=(f"{sum(counts.values()):,} repeated blank-node structures in "
                                    f"{len(counts)} file(s) are dropped; one copy of each stays, so "
                                    "no statement is lost."),
                       ops=[{"op": "merge_nodes", "args": {"mode": "bnodes", "files": sorted(counts),
                                                          "expect": counts}}],
                       preview={"counts": counts})
    return remedy(f, "mechanical", "Collapse duplicate blank nodes",
                  "Identical structures attached twice make counts and cardinality checks wrong.",
                  [opt])


LICENSE_HINTS = (
    (re.compile(r"Creative Commons Attribution 4\.0|CC[- ]BY[- ]4\.0", re.I),
     "https://creativecommons.org/licenses/by/4.0/"),
    (re.compile(r"CC0|Creative Commons Zero|Public Domain Dedication", re.I),
     "https://creativecommons.org/publicdomain/zero/1.0/"),
    (re.compile(r"Apache License,? Version 2\.0", re.I), "https://www.apache.org/licenses/LICENSE-2.0"),
    (re.compile(r"\bMIT License\b|Permission is hereby granted, free of charge", re.I),
     "https://spdx.org/licenses/MIT"),
)


def _license_iri(ctx):
    for f in ctx.rdf(("ontology", "vocabulary")):
        h = next((s for s in f.graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
        v = f.graph.value(h, DCTERMS.license) if h is not None else None
        if isinstance(v, URIRef):
            return str(v), f"the license of {f.path}"
    for f in ctx.art.text_files():
        if f.path.rsplit("/", 1)[-1].lower().startswith(("license", "licence", "copying")):
            text = f.text(200_000)
            for rx, iri in LICENSE_HINTS:
                if rx.search(text):
                    return iri, f"the text of {f.path}"
    return None, ""


@builder("W_HEADER")
def header(ctx, f):
    path = (f.get("files") or [None])[0]
    af = ctx.art.get(path) if path else None
    if af is None or af.graph is None or not ctx.writable(path):
        return None
    title = f.get("title", "")
    h = next((s for s in af.graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
    opts, it = [], letters()
    if h is None:
        guess = (ctx.owned_namespaces() or [""])[0].rstrip("#/")
        opts.append(RemedyOption(
            id=next(it), recommended=True, label="Add an owl:Ontology header",
            consequence="The file gets an ontology IRI; add a license and version afterwards.",
            ops=[{"op": "add_triples", "args": {"file": path, "turtle":
                  "{{value}} a <http://www.w3.org/2002/07/owl#Ontology> .\n"}}],
            input={"kind": "iri", "label": "Ontology IRI", "default": guess}))
        return remedy(f, "guided", f"Give {path} an ontology header",
                      "Without a header the file has no identity, version or license.", opts)
    if "license" in title:
        iri, source = _license_iri(ctx)
        tmpl = f"<{h}> <{DCTERMS.license}> {{{{value}}}} .\n"
        opts.append(RemedyOption(
            id=next(it), recommended=True, label="Add dcterms:license",
            consequence=("The header states the license" + (f", taken from {source}." if source else
                         ". Enter the license IRI.")),
            ops=[{"op": "add_triples", "args": {"file": path, "turtle": tmpl}}],
            input={"kind": "iri", "label": "License IRI", "default": iri or ""}))
    if "version iri" in title:
        info = af.graph.value(h, OWL.versionInfo)
        default = f"{h}/{info}" if info is not None else ""
        opts.append(RemedyOption(
            id=next(it), recommended=not opts, label="Add owl:versionIRI",
            consequence=("The header names the IRI of this version" +
                         (f", following owl:versionInfo {info}." if info is not None else
                          ". Enter the version IRI.")),
            ops=[{"op": "add_triples", "args": {"file": path,
                                                "turtle": f"<{h}> <{OWL.versionIRI}> {{{{value}}}} .\n"}}],
            input={"kind": "iri", "label": "Version IRI", "default": default}))
    if "creator" in title:
        opts.append(RemedyOption(
            id=next(it), recommended=True, label="Name a creator (dcterms:creator)",
            consequence="The header names who made the ontology.",
            ops=[{"op": "add_triples", "args": {"file": path,
                                                "turtle": f"<{h}> <{DCTERMS.creator}> {{{{value}}}} .\n"}}],
            input={"kind": "text", "label": "Creator", "default": ""}))
    if not opts:
        return None
    if len(opts) > 1:   # several gaps in one finding: one option that fills them all
        merged = RemedyOption(id="a", recommended=True, label="Fill every missing annotation",
                              consequence=" ".join(o.consequence for o in opts),
                              ops=[op for o in opts for op in o.ops],
                              input={"kind": "fields", "fields": [dict(o.input, slot=f"value{i}")
                                                                  for i, o in enumerate(opts)]})
        for i, op in enumerate(merged.ops):
            op["args"]["turtle"] = op["args"]["turtle"].replace("{{value}}", "{{value%d}}" % i)
        opts = [merged]
    return remedy(f, "mechanical", f"Complete the header of {path}",
                  "A release without license or version identity cannot be cited or reused safely.",
                  opts)


def _ci_slots(ctx, root=""):
    """Paths for a CI step, relative to the repository the CI file belongs to."""
    pre = root.rstrip("/") + "/" if root else ""

    def mine(paths):
        return [p[len(pre):] for p in paths if p.startswith(pre)]
    shapes = mine([x.path for x in ctx.art.by_role("shapes")])
    onto = mine([x.path for x in ctx.art.by_role("ontology")])
    data = mine([x.path for x in ctx.art.data_files()])
    globs = sorted({(p.rsplit("/", 1)[0] + "/*." + p.rsplit(".", 1)[-1]) if "/" in p else p for p in data})
    return {"shapes": shapes, "ontology": onto, "data": globs}


@builder("W_CI_NO_SHACL", "W_CI_NO_REASONER")
def ci_step(ctx, f):
    from ..audit.hygiene import _repo_root
    kind = "shacl" if f["code"] == "W_CI_NO_SHACL" else "reasoner"
    what = "SHACL validation of every data file" if kind == "shacl" else "a HermiT consistency check"
    gh = sorted(x.path for x in ctx.art.files if re.search(r"(^|/)\.github/workflows/[^/]+\.ya?ml$", x.path))
    gl = sorted(x.path for x in ctx.art.files if re.search(r"(^|/)\.gitlab-ci\.ya?ml$", x.path))

    def step_ops(paths, template):
        ops, lines, seen_roots = [], {}, set()
        for path in paths:
            root = _repo_root(path)
            if root in seen_roots:          # one step per repository
                continue
            slots = dict(_ci_slots(ctx, root), kind=kind)
            try:
                lines[path] = ci_commands(kind, slots)
            except Exception:  # noqa: BLE001 - nothing this CI could check
                continue
            seen_roots.add(root)
            ops.append({"op": "write_text", "args": {"path": path, "template": template, "slots": slots}})
        return ops, lines

    opts, it = [], letters()
    if gh:
        ops, lines = step_ops(gh, "ci_github_steps")
        if ops:
            opts.append(RemedyOption(
                id=next(it), recommended=True,
                label="Add a step to " + ", ".join(o["args"]["path"] for o in ops),
                consequence=f"CI runs {what} on every push, so a release that fails it cannot pass "
                            "unnoticed. Paths are relative to each workflow's repository. The step "
                            "needs network access in CI to install its tools.",
                ops=ops, preview={"lines": [x for v in lines.values() for x in v],
                                  "file": ", ".join(lines)}))
    if gl:
        ops, lines = step_ops(gl, "gitlab_job")
        if ops:
            opts.append(RemedyOption(
                id=next(it), recommended=not opts, label="Add a job to " + ", ".join(lines),
                consequence=f"GitLab CI runs {what} on every pipeline.", ops=ops,
                preview={"lines": [x for v in lines.values() for x in v], "file": ", ".join(lines)}))
    if not opts:
        target = ".github/workflows/release-checks.yml"
        slots = dict(_ci_slots(ctx), kind=kind)
        try:
            lines = ci_commands(kind, slots)
        except Exception:  # noqa: BLE001 - nothing to wire up
            return None
        opts.append(RemedyOption(
            id=next(it), recommended=True, label=f"Add a GitHub Actions workflow ({target})",
            consequence=f"CI runs {what} on every push. The step needs network access in CI to "
                        "install its tools.",
            ops=[{"op": "write_text", "args": {"path": target, "template": "ci_github_workflow",
                                               "slots": slots}}],
            preview={"lines": lines, "file": target}))
    return remedy(f, "mechanical", f"Make CI run {what}",
                  "Checks that only run on a laptop do not stop a broken release.", opts)


@builder("W_CONFIG")
def config(ctx, f):
    ev = f.get("evidence") or {}
    unmatched = ev.get("unmatched") or []
    cfg = next((x for x in ("audit.yaml", "audit.yml") if any(a.path == x for a in ctx.art.files)), None)
    if unmatched:
        import os
        cfg = cfg or next((n for n in ("audit.yaml", "audit.yml")
                           if os.path.isfile(os.path.join(ctx.art.root, n))), None)
        if cfg is None:
            return None
        entries = [{"code": e.get("code"), "file": e.get("file")} for e in unmatched]
        opt = RemedyOption(id="a", recommended=True, label=f"Remove the stale entries from {cfg}",
                           consequence=f"{len(entries)} declaration(s) that matched nothing are "
                                       "deleted, so the configuration only claims what happens.",
                           ops=[{"op": "write_text", "args": {"path": cfg, "template":
                                                              "audit_yaml_drop_expected",
                                                              "slots": {"entries": entries}}}],
                           preview={"entries": entries})
        return remedy(f, "mechanical", "Remove stale expected outcomes",
                      "A declaration that no longer matches can hide a future regression.", [opt])
    return remedy(f, "guided", "Correct the audit configuration",
                  "The configuration could not be read, so none of its settings applied.", [],
                  explanation=f.get("message", ""))


def build(ctx, finding):
    from . import catalog_choice, catalog_guided, catalog_lint  # noqa: F401 - registers builders
    fn = BUILDERS.get(finding["code"])
    if fn is None or finding.get("expected"):
        return None
    return fn(ctx, finding)
