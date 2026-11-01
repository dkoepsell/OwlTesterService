"""Apply a plan to a copy of the release, write the outputs, re-audit (spec 5 and 6).

Applies are deterministic: the same plan on the same release gives byte-identical
files and an identical repaired zip. A plan with no accepted remedy reproduces
the original files, which is also how a revert works (apply again without it).
"""

import difflib
import json
import os
import shutil
import zipfile

import rdflib

from . import ops as O
from .model import SEVERITY_RANK

ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class ApplyError(Exception):
    """The apply stopped; no output was written."""

    def __init__(self, message, code="E_APPLY"):
        super().__init__(message)
        self.code = code


def max_removed():
    return float(os.environ.get("REPAIR_MAX_REMOVED", "0.02"))


# -- release copies ----------------------------------------------------------------------

def materialize(release, dest):
    """Lay the release out under ``dest`` exactly as the audit saw it."""
    from ..audit.files import extract_zip
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    items = release if isinstance(release, (list, tuple)) else [release]
    if len(items) == 1 and os.path.isdir(items[0]):
        shutil.rmtree(dest)
        shutil.copytree(items[0], dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return os.path.basename(os.path.abspath(items[0]).rstrip(os.sep))
    if len(items) == 1 and zipfile.is_zipfile(items[0]):
        top = extract_zip(items[0], dest)
        return top or os.path.splitext(os.path.basename(items[0]))[0]
    for p in items:
        shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
    return ""


def deterministic_zip(root, zpath, top):
    files = O.Tree(root).files()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            info = zipfile.ZipInfo((top + "/" if top else "") + rel, date_time=ZIP_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(root, *rel.split("/")), "rb") as fh:
                zf.writestr(info, fh.read())


# -- the removal bound -------------------------------------------------------------------

def _op_files(op):
    a = op.get("args") or {}
    out = [a[k] for k in ("file", "path") if a.get(k)] + list(a.get("files") or [])
    if op.get("op") == "exclude_file" and a.get("mode") == "legacy":
        out.append("legacy/" + a["path"])
    return out


def _added_keys(op):
    a = op.get("args") or {}
    keys = set()
    if op.get("op") != "add_triples":
        return keys
    if a.get("triples"):
        keys |= {(a["file"], str(r[0]), str(r[1])) for r in a["triples"]}
    elif a.get("turtle"):
        g = rdflib.Graph()
        try:
            g.parse(data=a["turtle"], format="turtle")
        except Exception:  # noqa: BLE001 - the op itself will report it
            return keys
        keys |= {(a["file"], O.n3(s), O.n3(p)) for s, p, _ in g}
    return keys


def removal_counts(remedies, roles):
    """Triples each role loses. A removal re-added with the same subject and
    predicate by the same remedy is a replacement, not a removal."""
    out = {"axioms": 0, "data": 0}
    for r in remedies:
        ops = r.decision.get("ops") or []
        replaced = set().union(*[_added_keys(o) for o in ops]) if ops else set()
        for o in ops:
            if o.get("op") != "remove_triples":
                continue
            a = o["args"]
            for row in a.get("triples") or []:
                # One axiom is one top-level statement: the triples hanging off its
                # blank nodes (a restriction's parts) are not counted again.
                if str(row[0]).startswith("_:") or (a["file"], str(row[0]), str(row[1])) in replaced:
                    continue
                out["data" if roles.get(a["file"]) == "data" else "axioms"] += 1
    return out


def check_bound(remedies, art):
    roles = {f.path: f.role for f in art.files}
    def statements(f):
        return sum(1 for s, _, _ in f.graph if not isinstance(s, rdflib.BNode)) if f.graph is not None else 0
    totals = {"axioms": sum(statements(f) for f in art.files if f.role in ("ontology", "vocabulary", "shapes")),
              "data": sum(statements(f) for f in art.files if f.role == "data")}
    ratio = max_removed()
    removed = removal_counts(remedies, roles)
    bounds = {k: max(1, int(totals[k] * ratio)) for k in totals}
    for k in removed:
        if removed[k] > bounds[k]:
            raise ApplyError(f"The plan removes {removed[k]} {k} triple(s); the bound is {bounds[k]} "
                             f"({ratio:.0%} of {totals[k]}). Choose fewer removals.", "E_OVER_RELAXED")
    return {"removed": removed, "bounds": bounds, "totals": totals, "ratio": ratio}


# -- diffs -------------------------------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return None
    except OSError:
        return ""


def _hunks(a, b, rel, old_exists, new_exists):
    al, bl = (a or "").splitlines(keepends=True), (b or "").splitlines(keepends=True)
    head = [f"diff --git a/{rel} b/{rel}\n"]
    if not old_exists:
        head.append("new file mode 100644\n")
    if not new_exists:
        head.append("deleted file mode 100644\n")
    body = []
    for line in difflib.unified_diff(al, bl, "a/" + rel if old_exists else "/dev/null",
                                     "b/" + rel if new_exists else "/dev/null"):
        body.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(head + body) if body else ""


def unified_patch(old_root, new_root, only=None):
    old_files, new_files = set(O.Tree(old_root).files()), set(O.Tree(new_root).files())
    names = sorted((old_files | new_files) if only is None else set(only))
    out = []
    for rel in names:
        a = _read(os.path.join(old_root, *rel.split("/"))) if rel in old_files else ""
        b = _read(os.path.join(new_root, *rel.split("/"))) if rel in new_files else ""
        if a is None or b is None:
            if rel not in old_files or rel not in new_files or \
                    open(os.path.join(old_root, *rel.split("/")), "rb").read() != \
                    open(os.path.join(new_root, *rel.split("/")), "rb").read():
                out.append(f"Binary files a/{rel} and b/{rel} differ\n")
            continue
        out.append(_hunks(a, b, rel, rel in old_files, rel in new_files))
    return "".join(out)


# -- before and after --------------------------------------------------------------------

PER_FILE = {"W_HEADER", "E_ABOX_INCONSISTENT", "E_PARSE", "E_SELF_EXAMPLE", "W_DOC_TERM"}


def _key(f):
    ev = f.get("evidence") or {}
    files = tuple(sorted(f.get("files") or ())) if f["code"] in PER_FILE else ()
    return (f["code"], f.get("iri") or "", str(ev.get("data_set") or ""),
            str(ev.get("wrong_namespace") or ""), files)


def compare(before, after, touched_findings=()):
    def live(rep):
        return {_key(f): f for f in rep.get("findings", []) if not f.get("expected")}
    b, a = live(before), live(after)
    expected_after = {_key(f): f for f in after.get("findings", []) if f.get("expected")}
    slim = (lambda f: {k: f.get(k) for k in ("id", "code", "severity", "title", "stage")})
    closed = [slim(f) for k, f in b.items() if k not in a and k not in expected_after]
    declared = [slim(f) for k, f in b.items() if k not in a and k in expected_after]
    remaining = [slim(a[k]) for k in b if k in a]
    new = [slim(f) for k, f in a.items() if k not in b]
    worst_closed = min((SEVERITY_RANK.get(f["severity"], 9) for f in closed + declared), default=9)
    flagged = [f for f in new if SEVERITY_RANK.get(f["severity"], 9) <= worst_closed]
    rank = {"pass": 0, "skipped": 0, "warn": 1, "fail": 2, "error": 3}
    touched_stages = {f.get("stage") for f in before.get("findings", []) if f.get("id") in set(touched_findings)}
    worse = []
    for code, st in (after.get("stages") or {}).items():
        was = (before.get("stages") or {}).get(code, {}).get("status")
        if code not in touched_stages and was is not None and \
                rank.get(st.get("status"), 0) > rank.get(was, 0):
            worse.append({"stage": code, "before": was, "after": st.get("status")})
    return {"closed": closed, "declared": declared, "remaining": remaining, "new": new,
            "flagged": flagged, "worse_untouched_stages": worse,
            "fixed": not flagged and not worse and not remaining_blocking(remaining),
            "verdict_before": before.get("verdict"), "verdict_after": after.get("verdict")}


def remaining_blocking(remaining):
    return any(f["severity"] in ("critical", "major") for f in remaining)


# -- applying ----------------------------------------------------------------------------

def selected(plan):
    return [r for r in plan.remedies if r.status in ("accepted", "applied") and r.decision
            and r.decision.get("ops")]


def _declare_op(plan, cfg_names):
    findings = {f["id"]: f for f in plan.audit_before.get("findings", [])}
    entries = []
    for r in plan.remedies:
        if r.status != "declared" or not r.decision:
            continue
        f = findings.get(r.finding_id) or {}
        files = f.get("files") or []
        entries.append({"code": r.code, "stage": f.get("stage"),
                        "file": files[0] if len(files) == 1 else None, "reason": r.decision.get("reason")})
    if not entries:
        return None
    if "audit.json" in cfg_names and not ({"audit.yaml", "audit.yml"} & cfg_names):
        return {"op": "write_text", "args": {"path": "audit.json", "template": "audit_json_expected",
                                             "slots": {"entries": entries}}}
    path = "audit.yml" if "audit.yml" in cfg_names and "audit.yaml" not in cfg_names else "audit.yaml"
    return {"op": "write_text", "args": {"path": path, "template": "audit_yaml_expected",
                                         "slots": {"entries": entries}}}


def _trim(args):
    out = {}
    for k, v in args.items():
        if isinstance(v, list) and len(v) > 20:
            out[k] = v[:20] + [f"... {len(v) - 20} more"]
        elif isinstance(v, str) and len(v) > 2000:
            out[k] = v[:2000] + "..."
        else:
            out[k] = v
    return out


def run_ops(plan, tree, guard):
    """Apply every accepted remedy; return (fixlog entries, per-remedy patches)."""
    log, patches = [], {}
    chosen = selected(plan)
    for r in chosen:
        d = r.decision
        before_r = {}
        for op in d["ops"]:
            for rel in _op_files(op):
                if rel not in before_r:
                    before_r[rel] = tree.read(rel) if tree.exists(rel) else None
        for op in d["ops"]:
            files = _op_files(op)
            snap = {rel: (tree.read(rel) if tree.exists(rel) else "") for rel in files}
            try:
                rec = O.run(tree, op, guard)
            except O.OpError as e:
                raise ApplyError(f"{r.id} ({r.title}): {e}")
            lines = sum(O.line_delta(snap[rel], tree.read(rel) if tree.exists(rel) else "") for rel in files)
            log.append({"op": op["op"], "args": _trim(op.get("args") or {}), "files": files,
                        "triples_added": rec.get("triples_added", 0),
                        "triples_removed": rec.get("triples_removed", 0), "lines_changed": lines,
                        "counts": {k: v for k, v in rec.items() if k not in ("triples_added", "triples_removed")},
                        "finding_id": r.finding_id, "remedy_id": r.id, "option": d.get("option"),
                        "by": d.get("by"), "at": d.get("at"), "note": d.get("note", ""),
                        "ai_assisted": bool(d.get("ai_assisted"))})
        parts = []
        for rel, old in sorted(before_r.items()):
            new = tree.read(rel) if tree.exists(rel) else None
            if old != new:
                parts.append(_hunks(old or "", new or "", rel, old is not None, new is not None))
        patches[r.id] = "".join(parts)
    return log, patches


def fixlog_md(plan, log, result):
    lines = [f"# Fix log: {plan.artifact}", "",
             f"Plan {plan.plan_id[:8]}, built from the audit of {plan.audit_before.get('audited_at', '')}.", ""]
    by_remedy = {}
    for e in log:
        by_remedy.setdefault(e["remedy_id"], []).append(e)
    for r in plan.remedies:
        if r.id not in by_remedy and r.status not in ("declared", "skipped"):
            continue
        lines.append(f"## {r.title} ({r.code}, finding {r.finding_id})")
        d = r.decision or {}
        who = (d.get("by") or {}).get("name") or "unknown"
        if r.status == "declared":
            lines.append(f"Declared expected by {who} on {d.get('at')}: {d.get('reason')}")
        elif r.status == "skipped":
            lines.append(f"Skipped by {who} on {d.get('at')}" + (f": {d['note']}" if d.get("note") else "."))
        else:
            opt = r.option(d.get("option") or "")
            lines.append(f"Chose ({d.get('option')}) {opt.label if opt else ''}, by {who} on {d.get('at')}"
                         + (" with AI assistance" if d.get("ai_assisted") else "") + ".")
            if d.get("note"):
                lines.append(f"Note: {d['note']}")
            for e in by_remedy.get(r.id, []):
                lines.append(f"- `{e['op']}` on {', '.join(e['files'])}: +{e['triples_added']} / "
                             f"-{e['triples_removed']} triples, {e['lines_changed']} lines changed")
        lines.append("")
    if result:
        lines += ["## Verification", "",
                  f"Verdict before: {result.get('verdict_before')}; after: {result.get('verdict_after')}.",
                  f"Closed: {len(result.get('closed', []))}; declared expected: {len(result.get('declared', []))}; "
                  f"remaining: {len(result.get('remaining', []))}; new: {len(result.get('new', []))}.", ""]
    return "\n".join(lines) + "\n"


def changelog_draft(plan, log):
    items = []
    for r in selected(plan):
        opt = r.option(r.decision.get("option") or "")
        items.append(f"- {r.title}: {opt.label if opt else ''} (audit finding {r.finding_id}).")
    for r in plan.remedies:
        if r.status == "declared":
            items.append(f"- Declared {r.code} expected: {(r.decision or {}).get('reason', '')}")
    return "## Unreleased\n\n" + ("\n".join(items) or "- No changes.") + "\n"


def apply_plan(plan, release, out_dir, *, reaudit=True, progress=None, audit_options=None):
    """Apply ``plan`` to ``release``; outputs go to ``out_dir/out``. Returns the result."""
    from ..audit.artifact import load_artifact
    from ..audit.references import declared_terms
    progress = progress or (lambda stage: None)
    work, original, out = (os.path.join(out_dir, x) for x in ("work", "original", "out"))
    progress("copying the release")
    top = materialize(release, original)
    materialize(release, work)
    art = load_artifact(original)
    try:
        bound = check_bound(selected(plan), art)
        guard = {"owned": [ns for ns in art.owned_namespaces] +
                 [b + s for b in art.owned_bases for s in ("#", "/")],
                 "declared": sorted({str(s) for f in art.rdf_files() if f.graph is not None
                                     for s in f.graph.subjects() if isinstance(s, rdflib.URIRef)}
                                    | {str(t) for t in declared_terms(art)})}
        cfg_names = {f for f in os.listdir(original) if f in ("audit.yaml", "audit.yml", "audit.json")}
    finally:
        art.cleanup()
    tree = O.Tree(work)
    progress("applying the accepted changes")
    try:
        log, patches = run_ops(plan, tree, guard)
        dop = _declare_op(plan, cfg_names)
        if dop is not None:
            snap = tree.read(dop["args"]["path"]) if tree.exists(dop["args"]["path"]) else ""
            O.run(tree, dop, guard)
            log.append({"op": "write_text", "args": _trim(dop["args"]), "files": [dop["args"]["path"]],
                        "triples_added": 0, "triples_removed": 0,
                        "lines_changed": O.line_delta(snap, tree.read(dop["args"]["path"])),
                        "counts": {}, "finding_id": None, "remedy_id": "declared", "option": None,
                        "by": None, "at": None, "note": "expected outcomes declared in the plan",
                        "ai_assisted": False})
    except (ApplyError, O.OpError) as e:
        shutil.rmtree(work, ignore_errors=True)
        raise ApplyError(str(e), getattr(e, "code", "E_APPLY"))
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    name = plan.artifact or top or "release"
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in name)[:80] or "release"
    deterministic_zip(work, os.path.join(out, f"{safe}-repaired.zip"), top)
    with open(os.path.join(out, "repair.patch"), "w", encoding="utf-8") as fh:
        fh.write(unified_patch(original, work))
    with open(os.path.join(out, "patches.json"), "w", encoding="utf-8") as fh:
        json.dump(patches, fh)
    with open(os.path.join(out, "audit-before.json"), "w", encoding="utf-8") as fh:
        json.dump(plan.audit_before, fh, indent=1)
    result = {"applied": [r.id for r in selected(plan)], "bound": bound,
              "outputs": {"zip": f"{safe}-repaired.zip", "patch": "repair.patch",
                          "fixlog_json": "FIXLOG.json", "fixlog_md": "FIXLOG.md",
                          "changelog": "CHANGELOG-draft.md", "audit_before": "audit-before.json"}}
    if reaudit:
        progress("auditing the patched copy")
        from ..audit.runner import run_audit
        after = run_audit(work, profile=plan.profile, artifact_name=plan.artifact,
                          **(audit_options or {})).to_dict()
        with open(os.path.join(out, "audit-after.json"), "w", encoding="utf-8") as fh:
            json.dump(after, fh, indent=1)
        result["outputs"]["audit_after"] = "audit-after.json"
        result.update(compare(plan.audit_before, after, [r.finding_id for r in selected(plan)]))
        result["scorecards"] = {"before": plan.audit_before.get("scorecard", []),
                                "after": after.get("scorecard", [])}
    with open(os.path.join(out, "FIXLOG.json"), "w", encoding="utf-8") as fh:
        json.dump({"plan_id": plan.plan_id, "artifact": plan.artifact, "entries": log}, fh, indent=1)
    with open(os.path.join(out, "FIXLOG.md"), "w", encoding="utf-8") as fh:
        fh.write(fixlog_md(plan, log, result))
    with open(os.path.join(out, "CHANGELOG-draft.md"), "w", encoding="utf-8") as fh:
        fh.write(changelog_draft(plan, log))
    shutil.rmtree(original, ignore_errors=True)
    return result
