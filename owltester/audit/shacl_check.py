"""R4: SHACL with the artifact's own shapes.

Shapes are linted first. Each data file, and the vocabularies, are validated
against the artifact's (primary) shapes with the ontology and vocabularies as
the ontology graph and RDFS inference. Violations are aggregated per data set
by (shape, path, constraint); a violation whose value is a dangling reference
explained by R5 is linked to that finding after R5 runs (see ``link``).
"""

from collections import Counter

from .. import errors
from .context import TimedOut, run_with_timeout


def _validate(ctx, data, shapes, ont):
    import shacl_tools
    return run_with_timeout(shacl_tools.validate, ctx.budget.cap("shacl"),
                            data, shapes, ont_graph=ont, inference="rdfs")


def _own_subjects(graph):
    return {str(s) for s in graph.subjects()}


def _aggregate(results):
    groups = {}
    for x in results:
        key = (x.get("source_shape") or "", x.get("path_label") or x.get("path") or "",
               x.get("constraint") or "")
        g = groups.setdefault(key, {"shape": key[0], "path": key[1], "constraint": key[2],
                                    "count": 0, "examples": [], "values": Counter(),
                                    "message": x.get("message", "")})
        g["count"] += 1
        if len(g["examples"]) < 2 and x["focus_label"] not in g["examples"]:
            g["examples"].append(x["focus_label"])
        if x.get("value"):
            g["values"][x["value"]] += 1
    out = sorted(groups.values(), key=lambda g: -g["count"])
    for g in out:
        g["values"] = [v for v, _ in g["values"].most_common(3)]
    return out


def run_r4(ctx):
    import shacl_tools
    art = ctx.artifact
    shapes_files = art.by_role("shapes")
    external = art.by_role("shapes", scope="external")
    if not shapes_files:
        ctx.skip("R4", "SHACL with the artifact's own shapes",
                 "The artifact ships no shapes of its own."
                 + (f" ({len(external)} shapes file(s) target other namespaces.)" if external else ""))
        return
    shapes = art.shapes_graph()
    tbox = art.tbox()
    issues = shacl_tools.lint_shapes(shapes, tbox)
    if issues:
        errs = [i for i in issues if i["level"] == "error"]
        ctx.add("R4", errors.I_SHAPES_LINT, "major" if errs else "info",
                f"{len(issues)} problem(s) in the shapes themselves",
                files=[f.path for f in shapes_files], count=len(issues),
                evidence={"issues": issues[:30]},
                fix="Fix malformed shapes first; a broken shape silently checks nothing.")

    notes = {"data_sets": {}, "external_shapes": [f.path for f in external]}
    shacl_values = ctx.cache.setdefault("shacl_values", {})
    sets = [(name, art.data_files(name), art.data_sets[name]["legacy"]) for name in sorted(art.data_sets)]
    vocab_files = art.by_role("vocabulary")
    for name, files, legacy in sets + ([("vocabularies", vocab_files, False)] if vocab_files else []):
        ctx.progress("R4", name)
        failing, results = [], []
        for f in files:
            if ctx.budget.expired():
                ctx.limit("R4", "total", f"{f.path} not validated")
                continue
            try:
                rep = _validate(ctx, f.graph, shapes, tbox)
            except TimedOut as e:
                ctx.limit("R4", "shacl", f"{f.path}: {e}")
                continue
            except Exception as e:  # noqa: BLE001 - pySHACL reports bad shapes this way
                ctx.limit("R4", "shacl", f"{f.path}: validation could not run ({str(e)[:200]})")
                continue
            mine = _own_subjects(f.graph)
            res = [x for x in rep["results"] if x["severity"] == "Violation"
                   and x["focus_node"] in mine]
            if res:
                failing.append(f.path)
                for x in res:
                    x["file"] = f.path
                results.extend(res)
        notes["data_sets"][name] = {"files": len(files), "failing": len(failing),
                                    "violations": len(results)}
        if not results:
            continue
        everyone = len(failing) == len(files)
        severity = "critical" if everyone and not legacy and name != "vocabularies" else "major"
        groups = _aggregate(results)
        what = "vocabulary files" if name == "vocabularies" else f"data set {name}"
        f_obj = ctx.add(
            "R4", errors.E_SHACL, severity,
            f"{what}: {len(failing)} of {len(files)} files fail the artifact's own shapes "
            f"({len(results):,} violations)",
            ("Every file in this published data set fails the shapes shipped with it. "
             if severity == "critical" else "") +
            "Most common: " + "; ".join(f"{g['shape']} {g['path']} {g['constraint']} "
                                        f"({g['count']})" for g in groups[:3]) + ".",
            files=failing, count=len(results),
            evidence={"data_set": name, "files_total": len(files), "files_failing": len(failing),
                      "legacy": legacy, "groups": groups[:25]},
            fix="Fix the data (or the shapes, if they are wrong) so that the release validates; "
                "then make CI run SHACL on every data file.")
        shacl_values[f_obj.id] = Counter(x["value_iri"] for x in results if x.get("value_iri"))

    total = sum(v["violations"] for v in notes["data_sets"].values())
    summary = "; ".join(f"{k}: {v['failing']}/{v['files']} files fail ({v['violations']})"
                        for k, v in notes["data_sets"].items())
    ctx.finish("R4", "SHACL with the artifact's own shapes",
               summary=(summary or "No data to validate.") +
               (f" {len(external)} shapes file(s) for other namespaces were not used." if external else ""),
               notes=dict(notes, total_violations=total))


def link(ctx):
    """After R5: tie SHACL violations to the reference finding that explains them."""
    explained = ctx.cache.get("dangling_owner", {})   # dangling IRI -> R5 finding id
    by_id = {f.id: f for f in ctx.findings}
    for fid, values in ctx.cache.get("shacl_values", {}).items():
        f = by_id.get(fid)
        if f is None or not explained:
            continue
        hits = Counter()
        for iri, n in values.items():
            if iri in explained:
                hits[explained[iri]] += n
        if not hits:
            continue
        linked = sum(hits.values())
        f.related = sorted(set(f.related) | set(hits))
        share = f"All {linked:,}" if linked == f.count else f"{linked:,} of {f.count:,}"
        f.evidence["explained_by"] = dict(hits)
        f.message = (f"{share} violations are caused by "
                     + ", ".join(f"finding {k}" for k in sorted(hits)) + ". " + f.message)
