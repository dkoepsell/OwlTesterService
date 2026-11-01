"""The release builder (SPEC-release.md, Part B): OWL file in, audited release out.

    build(input, answers, out_dir, ...) -> build report (also out_dir/build-report.json)

Outputs in ``out_dir``:
    release/<name>-<version>/   the release (what the zip holds)
    <name>-<version>.zip        the audited release, deterministic
    <name>-repo.zip             the repository scaffold (section 9.8)
    w3id/                       .htaccess and the w3id.org pull-request text (section 11)
    drafts/                     starters not shipped (the SHACL scaffold by default)
    build-report.json

No network: every import is resolved locally and ROBOT runs with the catalog.
Timestamps inside the release are the release date, so the same inputs and
answers give byte-identical zips.
"""

import json
import os
import shutil
import sys
import time

from . import answers as A
from . import docs, gate, imports, jsonld, metadata, package, quality, record, robot

STEPS = ("metadata", "imports", "build", "docs", "quality", "audit", "package", "scaffold")


def _previous(previous_zip, name, work):
    """(graph, version, changelog text, path) of the previous release's full ontology."""
    root, cleanup = record.open_release(previous_zip)
    try:
        candidates = [os.path.join(root, f"{name}.owl")] + sorted(
            ab for rel, ab in record.list_files(root) if rel.endswith((".owl", ".ttl")) and "/" not in rel)
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                g = metadata.read(path)
            except metadata.InputError:
                continue
            h = metadata.header(g)
            if h.get("ontology_iri"):
                log = ""
                if os.path.isfile(os.path.join(root, "CHANGELOG.md")):
                    with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as fh:
                        log = fh.read()
                keep = os.path.join(work, "previous" + os.path.splitext(path)[1])
                shutil.copyfile(path, keep)
                return g, h.get("version"), log, keep, cleanup
    except Exception:
        cleanup()
        raise
    cleanup()
    return None, None, "", None, (lambda: None)


TIMING_KEYS = ("elapsed_seconds", "elapsed", "duration_seconds")


def _reproducible(obj):
    """The audit report without wall-clock timings, so the release is byte-identical."""
    if isinstance(obj, dict):
        return {k: _reproducible(v) for k, v in obj.items() if k not in TIMING_KEYS}
    if isinstance(obj, list):
        return [_reproducible(v) for v in obj]
    return obj


def _copy_inputs(paths, release_dir, sub):
    out = []
    for p in paths:
        rel = f"{sub}/{os.path.basename(p)}"
        os.makedirs(os.path.join(release_dir, sub), exist_ok=True)
        shutil.copyfile(p, os.path.join(release_dir, rel))
        out.append(rel)
    return sorted(out)


def build(input_path, answers, out_dir, *, supplied_imports=(), shapes=(), vocabs=(), examples=(),
          previous=None, audit=True, progress=None, budget=300, audit_budget=None):
    a = answers if isinstance(answers, dict) and answers.get("_validated") else A.validate(answers)
    a = {k: v for k, v in a.items() if k != "_validated"}
    step = progress or (lambda name, note="": None)
    log, warnings = [], []
    clock = robot.Budget(budget)
    started = time.time()
    name, version = a["name"], a["version"]
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    shutil.rmtree(work, ignore_errors=True)
    release_dir = os.path.join(out_dir, "release", f"{name}-{version}")
    shutil.rmtree(os.path.join(out_dir, "release"), ignore_errors=True)
    os.makedirs(release_dir)
    report = {"status": "running", "answers": a, "steps": {}, "warnings": warnings, "log": log}

    # 1. metadata
    step("metadata", "reading the ontology")
    g = metadata.read(input_path)
    report["header"] = metadata.header(g)
    ns = metadata.check_namespace(g, a["ontology_iri"], a["base"])
    report["namespace"] = ns
    if not ns["ok"]:
        warnings.append("Some of the ontology's own terms are outside its base "
                        f"({', '.join(list(ns['outside_base'])[:3])}): the namespace problem LOMO had.")
    term_ns = next(iter(ns["namespaces"]), a["base"] + "/")

    # 2. imports and BFO
    step("imports", "resolving imports")
    edit_dir = os.path.join(work, "ontology")
    os.makedirs(edit_dir)
    info = imports.resolve(g, supplied_imports, a, edit_dir, clock, log)
    report["imports"] = dict(info, detected=imports.detect(g))
    metadata.apply_header(g, a, info["imports"])
    staged = os.path.join(edit_dir, ".input.nt")
    g.serialize(staged, format="nt", encoding="utf-8")
    edit = os.path.join(edit_dir, f"{name}-edit.ttl")
    catalog = os.path.join(edit_dir, "catalog-v001.xml")
    robot.convert(staged, edit, clock, log, catalog=catalog)
    os.remove(staged)

    # 3. build with ROBOT
    step("build", "base, full (HermiT) and formats")
    full, base = f"{name}.owl", f"{name}-base.owl"
    robot.build_base(edit, catalog, os.path.join(release_dir, base), a, clock, log)
    robot.build_full(edit, catalog, os.path.join(release_dir, full), a, clock, log)
    robot.convert(os.path.join(release_dir, full), os.path.join(release_dir, f"{name}.ttl"), clock, log)
    formats = []
    if "ofn" in a["formats"]:
        robot.convert(os.path.join(release_dir, full), os.path.join(release_dir, f"{name}.ofn"), clock, log)
        formats.append(f"{name}.ofn")
    built = metadata.read(os.path.join(release_dir, f"{name}.ttl"))
    if "jsonld" in a["formats"]:
        package.write(os.path.join(release_dir, f"{name}.jsonld"), jsonld.dumps(built))
        formats.append(f"{name}.jsonld")

    # 4. documentation
    step("docs", "README, terms, diagram, CHANGELOG")
    terms_text, gaps = docs.terms_md(built, a)
    package.write(os.path.join(release_dir, "docs", "terms.md"), terms_text)
    package.write(os.path.join(release_dir, "docs", "diagram.svg"), docs.diagram_svg(built, a))
    report["gaps"] = gaps
    if gaps["label"] or gaps["definition"]:
        warnings.append(f"{len(gaps['label'])} term(s) without a label and {len(gaps['definition'])} without "
                        "a definition; listed in docs/terms.md for you to fill.")
    changes, diff_md, prev_log, suggestion = None, "", "", None
    if previous:
        pg, pv, prev_log, prev_path, cleanup = _previous(previous, name, work)
        try:
            if pg is not None:
                stem = a["base"].rsplit("/", 1)[0] + "/"
                own = lambda iri: iri.startswith(term_ns) or iri.startswith(stem)
                v, why, changes = robot.suggest_version(pg, built, pv, own)
                changes["reason"] = why
                suggestion = {"previous": pv, "suggested": v, "reason": why,
                              "added": len(changes["added"]), "removed": len(changes["removed"])}
                diff_md = robot.diff(prev_path, os.path.join(release_dir, full),
                                     os.path.join(work, "diff.md"), clock, log)
                if v != version:
                    warnings.append(f"The diff against {pv} suggests version {v} ({why}); you chose {version}.")
            else:
                warnings.append("The previous release has no ontology the builder could read.")
        finally:
            cleanup()
    report["version_suggestion"] = suggestion
    package.write(os.path.join(release_dir, "CHANGELOG.md"), docs.changelog(a, changes, diff_md, prev_log))

    # 5. quality layer and the supplied files
    step("quality", "QC queries, competency questions, shapes")
    qc = quality.qc_queries(a, term_ns)
    cq = quality.cq_starters(a)
    report["qc"] = quality.run_qc(built, qc)
    for fname, text in sorted(qc.items()):
        package.write(os.path.join(release_dir, "sparql", fname), text)
    for fname, text in sorted(cq.items()):
        package.write(os.path.join(release_dir, "sparql", "cq", fname), text)
    layout = {"full": full, "base": base, "formats": formats,
              "shapes": _copy_inputs(shapes, release_dir, "shapes"),
              "vocabularies": _copy_inputs(vocabs, release_dir, "vocab"),
              "examples": _copy_inputs(examples, release_dir, "examples")}
    scaffold = quality.shapes_scaffold(built, a) if a["shapes_scaffold"] != "off" else None
    if scaffold and a["shapes_scaffold"] == "include":
        rel = f"shapes/{name}-shapes.ttl"
        package.write(os.path.join(release_dir, rel), scaffold)
        layout["shapes"] = sorted(layout["shapes"] + [rel])
    elif scaffold:
        package.write(os.path.join(out_dir, "drafts", f"{name}-shapes.draft.ttl"), scaffold)
    readme_files = [(full, "merged with its imports and reasoned (HermiT)"),
                    (base, "this ontology's own axioms only"), (f"{name}.ttl", "the full ontology as Turtle")]
    readme_files += [(f, "the full ontology in another format") for f in formats]
    readme_files += [(r, "SHACL shapes") for r in layout["shapes"]]
    readme_files += [(r, "controlled vocabulary") for r in layout["vocabularies"]]
    readme_files += [(r, "example data") for r in layout["examples"]]
    readme_files += [("docs/terms.md", "every term with its label, BFO parent and definition"),
                     ("docs/diagram.svg", "the class hierarchy"),
                     ("sparql/", "QC checks and competency-question starters"),
                     ("VERIFICATION.md", "the audit result and the checksum of every file")]
    package.write(os.path.join(release_dir, "README.md"), docs.readme(a, readme_files))
    package.write(os.path.join(release_dir, "LICENSE"), docs.license_text(a))
    package.write(os.path.join(release_dir, "NOTICE"), docs.notice(a, list(info["files"].values())))
    package.write(os.path.join(release_dir, "CITATION.cff"), docs.citation_cff(a))

    # 6. audit
    package.write(os.path.join(release_dir, "audit.yaml"), package.audit_yaml(a, layout))
    package.write(os.path.join(release_dir, package.MANIFEST), package.manifest(release_dir))
    if audit:
        step("audit", "full audit of the assembled release")
        from ..audit.runner import run_audit
        result = run_audit(release_dir, profile=a["profile"], budget=audit_budget,
                           artifact_name=f"{name}-{version}").to_dict()
        result = _reproducible(result)
        result["audited_at"] = f"{a['release_date']}T00:00:00+00:00"   # reproducible (see the docstring)
        stop = gate.blocking(result, a["fail_on"])
        report["audit"] = {"verdict": result["verdict"], "counts": gate.counts(result),
                           "gate": "rejected" if stop else "passed", "fail_on": a["fail_on"],
                           "blocking": [{"code": f["code"], "severity": f["severity"], "title": f["title"]}
                                        for f in stop]}
        # 7. package
        step("package", "verification record and zip")
        rec = record.make_record(release_dir, result, name=name, version=version, tag=f"v{version}",
                                 repository=a["repository"], fail_on=a["fail_on"])
        record.write_record(release_dir, rec)
    else:
        report["audit"] = None
    zpath = package.deterministic_zip(release_dir, os.path.join(out_dir, f"{name}-{version}.zip"),
                                      top=f"{name}-{version}")

    # 8. repository scaffold and w3id
    step("scaffold", "repository and persistent IRIs")
    repo = os.path.join(work, "repo")
    package.repo_scaffold(repo, a, release_dir, edit_dir, layout, qc, cq)
    rpath = package.deterministic_zip(repo, os.path.join(out_dir, f"{name}-repo.zip"), top=name)
    w3 = package.w3id(a)
    shutil.rmtree(os.path.join(out_dir, "w3id"), ignore_errors=True)
    for fname, text in w3.items():
        package.write(os.path.join(out_dir, "w3id", fname), text)

    report["outputs"] = {"zip": os.path.basename(zpath), "zip_sha256": package.sha256(zpath),
                         "repo_zip": os.path.basename(rpath), "repo_zip_sha256": package.sha256(rpath),
                         "release_dir": os.path.relpath(release_dir, out_dir),
                         "w3id": sorted(w3), "drafts": sorted(os.listdir(os.path.join(out_dir, "drafts")))
                         if os.path.isdir(os.path.join(out_dir, "drafts")) else []}
    report["status"] = "rejected" if report["audit"] and report["audit"]["gate"] == "rejected" else "done"
    report["seconds"] = round(time.time() - started, 1)
    with open(os.path.join(out_dir, "build-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    return report


def build_cli(args):
    """``owltester build``: exit 0 built and passed, 1 the gate rejected it, 2 input or tool errors."""
    from ..cli import ToolInputError
    try:
        a = A.load(args.answers)
    except A.AnswersError as e:
        raise ToolInputError("the answers are not valid:\n  " + "\n  ".join(e.problems)) from e
    for p in [args.input] + args.imports + args.shapes + args.vocab + args.examples + \
            ([args.previous] if args.previous else []):
        if not os.path.isfile(p):
            raise ToolInputError(f"No such file: {p}")

    def progress(name, note=""):
        if not args.quiet:
            print(f"  [{name}] {note}", file=sys.stderr)

    try:
        rep = build(args.input, a, args.out, supplied_imports=args.imports, shapes=args.shapes,
                    vocabs=args.vocab, examples=args.examples, previous=args.previous,
                    audit=not args.no_audit, progress=progress)
    except (metadata.InputError, imports.ImportError_) as e:
        raise ToolInputError(str(e)) from e
    except robot.RobotError as e:
        print(f"build: FAILED: {e}", file=sys.stderr)
        return 1
    for w in rep["warnings"]:
        print(f"  warning: {w}", file=sys.stderr)
    au = rep["audit"]
    print(f"build: {rep['status']}: {rep['outputs']['zip']}"
          + (f", audit {au['verdict']} ({gate.counts_line({'severity_counts': au['counts']})}), "
             f"gate --fail-on {au['fail_on']} {au['gate']}" if au else ", not audited"), file=sys.stderr)
    return 1 if rep["status"] == "rejected" else 0


def repackage(out_dir, repaired_zip, answers, audit_budget=None):
    """After guided repair (section 9.6): take the repaired release, audit it again, and
    write the record, MANIFEST and zip anew. The build report gains a ``repaired`` entry."""
    from ..audit.files import extract_zip
    from ..audit.runner import run_audit
    a = A.validate(answers)
    name, version = a["name"], a["version"]
    release_dir = os.path.join(out_dir, "release", f"{name}-{version}")
    staged = release_dir + ".repaired"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    extract_zip(repaired_zip, staged)
    for rel in record.NOT_AUDITED + (package.MANIFEST,):
        if os.path.isfile(os.path.join(staged, rel)):
            os.remove(os.path.join(staged, rel))
    package.write(os.path.join(staged, package.MANIFEST), package.manifest(staged))
    result = _reproducible(run_audit(staged, profile=a["profile"], budget=audit_budget,
                                     artifact_name=f"{name}-{version}").to_dict())
    result["audited_at"] = f"{a['release_date']}T00:00:00+00:00"
    rec = record.make_record(staged, result, name=name, version=version, tag=f"v{version}",
                             repository=a["repository"], fail_on=a["fail_on"])
    record.write_record(staged, rec)
    shutil.rmtree(release_dir, ignore_errors=True)
    os.replace(staged, release_dir)
    zpath = package.deterministic_zip(release_dir, os.path.join(out_dir, f"{name}-{version}.zip"),
                                      top=f"{name}-{version}")
    path = os.path.join(out_dir, "build-report.json")
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    stop = gate.blocking(result, a["fail_on"])
    report["audit"] = {"verdict": result["verdict"], "counts": gate.counts(result),
                       "gate": "rejected" if stop else "passed", "fail_on": a["fail_on"],
                       "blocking": [{"code": f["code"], "severity": f["severity"], "title": f["title"]}
                                    for f in stop]}
    report["repaired"] = True
    report["status"] = "rejected" if stop else "done"
    report["outputs"].update(zip=os.path.basename(zpath), zip_sha256=package.sha256(zpath))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    return report
