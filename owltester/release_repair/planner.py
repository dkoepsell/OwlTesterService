"""Build a fix plan from an audit report and record the user's decisions (spec 4)."""

import copy
import datetime
import re
import uuid

import rdflib
from rdflib import Literal

from .catalog import Ctx, build
from .catalog_guided import lens_gaps
from .model import SEVERITY_RANK, Plan
from .ops import OpError, term

IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+$")


class DecisionError(ValueError):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# -- building ----------------------------------------------------------------------------

def build_plan(report, release, *, job_id="", user=None, plan_id=None):
    """A Plan for ``report`` (an AuditReport dict) over ``release`` (zip, dir or files)."""
    from ..audit.artifact import load_artifact
    art = load_artifact(release)
    try:
        ctx = Ctx(art, report)
        remedies = []
        for f in report.get("findings", []):
            if f.get("expected"):
                continue
            try:
                r = build(ctx, f)
            except Exception as e:  # noqa: BLE001 - one bad builder must not cost the plan
                r = None
                import logging
                logging.getLogger(__name__).warning("remedy for %s failed: %s", f.get("id"), e)
            if r is not None:
                remedies.append(r)
        remedies += lens_gaps(ctx, report.get("lenses"))
        _link(remedies, report)
        remedies = order(remedies)
        # Ontology files first, so the default prefix is the ontology's own.
        graphs = [f.graph for role in ("ontology", "vocabulary", "shapes", "data", "other")
                  for f in ctx.rdf((role,))]
        seen, uniq = set(), []
        for g in graphs:
            for p, ns in sorted(g.namespaces(), key=lambda x: str(x[0])):
                if str(p) not in seen:
                    seen.add(str(p))
                    uniq.append([str(p), str(ns)])
        owned = list(art.owned_namespaces)
    finally:
        art.cleanup()
    user = user or {}
    return Plan(plan_id=plan_id or uuid.uuid4().hex, job_id=job_id, artifact=report.get("artifact", ""),
                profile=report.get("profile", "general"), created_at=now(),
                created_by={"user_id": user.get("user_id"), "name": user.get("name", "")},
                remedies=remedies, audit_before=report, prefixes=uniq, owned=owned)


def _link(remedies, report):
    """Causes before effects: the audit's ``related`` links, and datatype before range."""
    by_finding = {r.finding_id: r for r in remedies}
    findings = {f["id"]: f for f in report.get("findings", [])}
    for r in remedies:
        f = findings.get(r.finding_id) or {}
        deps = [by_finding[x].id for x in f.get("related") or [] if x in by_finding]
        if r.code == "W_RANGE":
            deps += [d.id for d in remedies if d.code == "E_DATATYPE_PROFILE"]
        r.depends_on = sorted(set(deps) - {r.id})


def order(remedies):
    """Critical first, then major, minor, info; within a severity, causes first."""
    ranked = sorted(remedies, key=lambda r: (SEVERITY_RANK.get(r.severity, 9), r.finding_id))
    ids = {r.id for r in ranked}
    out, placed = [], set()

    def place(r, stack=()):
        if r.id in placed or r.id in stack:
            return
        for d in r.depends_on:
            if d in ids:
                place(next(x for x in ranked if x.id == d), stack + (r.id,))
        placed.add(r.id)
        out.append(r)

    for r in ranked:
        place(r)
    return out


# -- deciding ----------------------------------------------------------------------------

def _actor(user):
    return {"user_id": (user or {}).get("user_id"), "name": (user or {}).get("name", "")}


def decide(plan, rid, action, *, option=None, content=None, note="", user=None, ai_assisted=False,
           prefixes=None, release=None):
    """Record a decision on one remedy. Returns the remedy."""
    r = plan.remedy(rid)
    if r is None:
        raise DecisionError("no such remedy")
    note = " ".join(str(note or "").split())[:2000]
    base = {"by": _actor(user), "at": now(), "note": note}
    if action == "accept":
        opt = r.option(str(option or ""))
        if opt is None:
            raise DecisionError("choose one of the options")
        prefixes = [tuple(x) for x in (plan.prefixes if prefixes is None else prefixes)]
        ops = fill_ops(opt, content, prefixes)
        if (opt.input or {}).get("validate") == "shapes" and release is not None:
            problems = check_example(release, _text(content), prefixes)
            if problems:
                raise DecisionError("The example still fails the shapes: " + "; ".join(problems[:5]))
        if not ops:
            raise DecisionError("this option changes nothing; skip the card instead")
        r.status, r.decision = "accepted", dict(base, option=opt.id, ops=ops, content=_short(content),
                                                ai_assisted=bool(ai_assisted))
    elif action == "skip":
        r.status, r.decision = "skipped", dict(base)
    elif action == "declare":
        if not note:
            raise DecisionError("declaring an outcome expected needs a written reason")
        r.status, r.decision = "declared", dict(base, reason=note)
    elif action in ("reopen", "revert"):
        if action == "revert" and r.status != "applied":
            raise DecisionError("only an applied remedy can be reverted")
        r.status, r.decision = ("reverted" if action == "revert" else "open"), \
            (dict(base, previous=r.decision) if action == "revert" else None)
    else:
        raise DecisionError(f"unknown action: {action!r}")
    plan.log.append({"remedy": rid, "action": action, "option": option, **base,
                     "ai_assisted": bool(ai_assisted)})
    return r


def _short(content):
    if isinstance(content, str):
        return content[:20000]
    return content


def _iri(value, what="IRI"):
    value = str(value or "").strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    if not IRI.match(value):
        raise DecisionError(f"enter an absolute {what}")
    return value


def _turtle(text, prefixes):
    text = str(text or "")
    if not text.strip():
        raise DecisionError("write the content first")
    head = "".join(f"@prefix {p}: <{ns}> .\n" for p, ns in prefixes
                   if not re.search(rf"(?i)@?prefix\s+{re.escape(p)}:", text))
    g = rdflib.Graph()
    try:
        g.parse(data=head + text, format="turtle")
    except Exception as e:  # noqa: BLE001
        raise DecisionError(f"the Turtle does not parse: {str(e)[:300]}")
    if not len(g):
        raise DecisionError("the Turtle has no statements")
    return head + text.strip() + "\n"


def _subst(obj, mapping):
    if isinstance(obj, str):
        for k, v in mapping.items():
            obj = obj.replace(k, v)
        return obj
    if isinstance(obj, list):
        return [_subst(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: _subst(v, mapping) for k, v in obj.items()}
    return obj


def _field_value(spec, value, in_turtle):
    if spec.get("kind") == "iri":
        iri = _iri(value)
        return f"<{iri}>" if in_turtle else iri
    text = " ".join(str(value or "").split())
    if not text:
        raise DecisionError(f"fill in {spec.get('label', 'the value')}")
    return Literal(text).n3()


def fill_ops(opt, content, prefixes=()):
    """The option's ops with the user's content in its slots, validated."""
    ops = copy.deepcopy(opt.ops)
    spec = opt.input or {}
    kind = spec.get("kind")
    if not kind:
        return ops
    if kind == "iri":
        iri = _iri(content if not isinstance(content, dict) else content.get("value"))
        rewrites = [o for o in ops if o["op"] == "rewrite_iri"]
        if rewrites and not iri.endswith(("/", "#")):
            raise DecisionError("a base IRI ends in / or #")
        out = []
        for o in ops:
            in_turtle = "turtle" in o["args"]
            out.append(_subst(o, {"{{value}}": f"<{iri}>" if in_turtle else iri}))
        return out
    if kind == "text":
        value = content if not isinstance(content, dict) else content.get("value")
        return _subst(ops, {"{{value}}": _field_value(spec, value, True)})
    if kind == "fields":
        content = content if isinstance(content, dict) else {}
        mapping = {}
        for i, field in enumerate(spec.get("fields", [])):
            mapping["{{value%d}}" % i] = _field_value(field, content.get(field.get("slot", f"value{i}")), True)
        return _subst(ops, mapping)
    if kind == "turtle":
        text = _turtle(content if not isinstance(content, dict) else content.get("value"), prefixes)
        return _subst(ops, {"{{content}}": text})
    if kind == "example":
        return _subst(ops, {"{{literal}}": _example_literal(spec, content, prefixes)})
    if kind == "table":
        return _table_ops(opt, ops, content)
    raise DecisionError(f"unknown input kind: {kind}")


def _example_literal(spec, content, prefixes):
    text = str(content if not isinstance(content, dict) else content.get("value") or "").strip()
    if not text:
        raise DecisionError("write the example first")
    from ..audit.files import parse_text_snippet
    g, err = parse_text_snippet(text, list(prefixes) + [("ex", "https://example.org/")])
    if g is None:
        raise DecisionError(f"the example does not parse as Turtle: {err[:300]}")
    lit = Literal(text, lang=spec.get("lang") or None)
    return lit.n3()


def _table_values(content):
    values = (content or {}).get("values") if isinstance(content, dict) else None
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values)}
    return {str(k): str(v or "").strip() for k, v in (values or {}).items() if str(v or "").strip()}


def _table_ops(opt, ops, content):
    rows = opt.input.get("rows") or []
    values = _table_values(content)
    if not values:
        raise DecisionError("fill in at least one row")
    tmpl = ops[0]
    picked = []
    for k, v in values.items():
        try:
            row = rows[int(k)]
        except (ValueError, IndexError):
            raise DecisionError(f"no row {k}")
        picked.append((row, v))
    if tmpl["op"] == "retype":
        allowed = {c["iri"] for c in opt.input.get("choices", [])}
        by = {}
        for row, v in picked:
            if v not in allowed:
                raise DecisionError(f"{v} is not one of the subclasses offered")
            by.setdefault((row["file"], v), []).append(f"<{row['subject']}>")
        return [{"op": "retype", "args": {"file": f, "from": tmpl["args"]["from"], "to": f"<{to}>",
                                          "subjects": sorted(subs)}}
                for (f, to), subs in sorted(by.items())]
    if tmpl["op"] == "add_triples":
        by = {}
        for row, v in picked:
            try:
                t = term(v)
            except OpError as e:
                raise DecisionError(f"row {row['label']}: {e}")
            by.setdefault(row["file"], []).append([f"<{row['subject']}>", f"<{row['property']}>", t.n3()])
        return [{"op": "add_triples", "args": {"file": f, "triples": rows_}} for f, rows_ in sorted(by.items())]
    if tmpl["op"] == "merge_nodes":
        mapping = {}
        for row, v in picked:
            mapping[row["subject"]] = _iri(v)
        return [{"op": "merge_nodes", "args": {"mode": "iris", "files": tmpl["args"]["files"],
                                               "mapping": mapping}}]
    raise DecisionError("this table has no change attached")


def _text(content):
    return str(content if not isinstance(content, dict) else content.get("value") or "")


def check_example(release, text, prefixes):
    """Violations the release's shapes report on the instances in an example."""
    import shacl_tools
    from ..audit.artifact import load_artifact
    from ..audit.files import parse_text_snippet
    g, err = parse_text_snippet(text, list(prefixes) + [("ex", "https://example.org/")])
    if g is None:
        return [f"it does not parse: {err[:200]}"]
    art = load_artifact(release)
    try:
        if not art.by_role("shapes"):
            return []
        res = shacl_tools.validate(g, art.shapes_graph(), ont_graph=art.tbox(), inference="rdfs")["results"]
    finally:
        art.cleanup()
    return [f"{x.get('focus_label')}: {x.get('path_label') or ''} {x.get('constraint')}"
            for x in res if x.get("severity") == "Violation"]
