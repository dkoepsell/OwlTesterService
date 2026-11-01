"""CLI gate — section 8 of the spec.

    owltester check  <artifact> --kernel sool-kernel.ttl [--all] [--json report.json]
    owltester repair <artifact> --kernel ... --out repaired.ttl --quarantine q.ttl
    owltester serve  --port 8080 --kernel ...
    owltester audit  <zip|dir|files...> [--profile general|bfo|sool] [--json f] [--html f] [--md f]
                     [--fail-on critical|major|minor] [--summary-md f]
    owltester record <release-dir> --report audit.json [--commit SHA] [--tag TAG] [--out VERIFICATION.json]
    owltester verify <release.zip|dir> [--reaudit]
    owltester build  <file.owl> --answers build.yaml --out dist/

Exit 0 == pass, 1 == the gate rejected it, 2 == usage or environment error (missing Java,
unreadable input), so CI can tell a bad release from a broken tool. For audit, the gate
is --fail-on (default critical: exit 1 only on a ``fail`` verdict). The non-zero exit on a hollowed-out artifact is
the whole point: CI and the corpus export pipeline abort before any FTP upload.
"""

import argparse
import json
import os
import sys

from . import errors
from .pipeline import check, baseline_for
from .repair import repair as repair_artifact
from .kernel import default_kernel_path


def _print_summary(report_dict, stream=sys.stderr):
    verdict = report_dict["verdict"]
    print(f"verdict: {verdict}", file=stream)
    for letter, st in report_dict["stages"].items():
        if st.get("skipped"):
            print(f"  [{letter}] skipped: {st['skipped']}", file=stream)
        elif st.get("pass"):
            print(f"  [{letter}] pass", file=stream)
        else:
            fails = ", ".join(st.get("failures", []))
            print(f"  [{letter}] FAIL: {fails}", file=stream)


def cmd_check(args):
    baseline = baseline_for(args.baseline) if args.baseline else None
    report = check(args.artifact, kernel_path=args.kernel, all_stages=args.all,
                   baseline_counts=baseline)
    d = report.to_dict()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    else:
        print(json.dumps(d, indent=2))
    _print_summary(d)
    return errors.EXIT_PASS if d["verdict"] == "pass" else errors.EXIT_FAIL


def cmd_repair(args):
    serialized, result = repair_artifact(
        args.artifact, kernel_path=args.kernel, max_removed=args.max_removed)

    if result["quarantine"] and args.quarantine:
        import rdflib
        qg = rdflib.Graph()
        for item in result["quarantine"]:
            # record quarantined edges as a reified note graph
            s = rdflib.BNode()
            qg.add((s, rdflib.RDFS.comment, rdflib.Literal(
                f"{item['axiom']} :: {item['justification']}")))
        qg.serialize(destination=args.quarantine, format="turtle")

    status = result["status"]
    print(json.dumps(result["report"], indent=2))
    _print_summary(result["report"])
    print(f"repair status: {status}", file=sys.stderr)
    if result.get("error"):
        print(f"repair error: {result['error']}", file=sys.stderr)

    if status == "repaired" and serialized and args.out:
        mode = "wb" if isinstance(serialized, bytes) else "w"
        with open(args.out, mode) as fh:
            fh.write(serialized)
        print(f"wrote repaired artifact: {args.out}", file=sys.stderr)

    return errors.EXIT_PASS if status in ("unchanged", "repaired") else errors.EXIT_FAIL


def cmd_audit(args):
    from .audit.render import to_html, to_markdown
    from .audit.runner import run_audit

    def progress(stage, note=""):
        if not args.quiet:
            print(f"  {stage} {note}".rstrip(), file=sys.stderr)

    from .release import gate
    from .release.tools import require_java
    require_java()
    missing = [a for a in args.artifact if not os.path.exists(a)]
    if missing:
        raise ToolInputError(f"No such file or directory: {missing[0]}")
    source = args.artifact if len(args.artifact) > 1 else args.artifact[0]
    report = run_audit(source, profile=args.profile, config_path=args.config, budget=args.budget,
                       max_explanations=args.max_explanations, explain=not args.no_explain,
                       progress=progress)
    d = report.to_dict()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(to_markdown(report))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(to_html(report))
    if not (args.json or args.md or args.html):
        print(json.dumps(d, indent=2))
    counts = d["severity_counts"]
    print(f"verdict: {d['verdict']} ({counts['critical']} critical, {counts['major']} major, "
          f"{counts['minor']} minor, {counts['info']} info)", file=sys.stderr)
    for row in d["scorecard"]:
        print(f"  [{row['stage']}] {row['status']}: {row['summary']}", file=sys.stderr)
    if args.summary_md:
        with open(args.summary_md, "w", encoding="utf-8") as fh:
            fh.write(gate.summary_md(d, args.fail_on))
    stop = gate.blocking(d, args.fail_on)
    if stop:
        print(f"gate --fail-on {args.fail_on}: rejected ({len(stop)} finding(s))", file=sys.stderr)
    return errors.EXIT_FAIL if stop else errors.EXIT_PASS


def cmd_record(args):
    from .release import record as rec
    if not os.path.isdir(args.release):
        raise ToolInputError(f"{args.release} is not a directory")
    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    r = rec.make_record(args.release, report, name=args.name, version=args.version, tag=args.tag,
                        commit=args.commit, repository=args.repository, fail_on=args.fail_on,
                        attest=args.attest)
    out_dir = os.path.dirname(os.path.abspath(args.out)) if args.out else os.path.abspath(args.release)
    if out_dir != os.path.abspath(args.release):
        raise ToolInputError("--out must name VERIFICATION.json at the root of the release")
    rec.write_record(args.release, r)
    print(rec.record_md(r).splitlines()[0], file=sys.stderr)
    return errors.EXIT_PASS


def cmd_verify(args):
    from .release import record as rec
    if not os.path.exists(args.release):
        raise ToolInputError(f"No such file or directory: {args.release}")
    if args.reaudit:
        from .release.tools import require_java
        require_java()
    try:
        res = rec.verify(args.release, reaudit=args.reaudit, allow=args.allow or ())
    except rec.RecordError as e:
        print(f"verify: FAILED: {e}", file=sys.stderr)
        return errors.EXIT_FAIL
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in res.items() if k != "record"}, fh, indent=2)
    a = res["record"]["audit"]
    for p in res["problems"]:
        print(f"  {p}", file=sys.stderr)
    state = "ok" if res["ok"] else "FAILED"
    print(f"verify: {state}: {len(res['record']['files'])} file(s), recorded verdict {a['verdict']}"
          + (f", re-audit verdict {res['reaudit']['verdict']}" if res["reaudit"] else ""), file=sys.stderr)
    return errors.EXIT_PASS if res["ok"] else errors.EXIT_FAIL


def cmd_build(args):
    from .release.builder import build_cli
    return build_cli(args)


def cmd_repair_plan(args):
    """Build a fix plan from an audit report (JSON) and the release it audited."""
    from .release_repair.planner import build_plan
    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    release = args.release if len(args.release) > 1 else args.release[0]
    plan = build_plan(report, release, user={"user_id": None, "name": os.environ.get("USER", "cli")})
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan.to_dict(), fh, indent=1)
    for r in plan.remedies:
        print(f"{r.id}\t{r.severity}\t{r.kind}\t{r.title}", file=sys.stderr)
    print(f"{len(plan.remedies)} remedies written to {args.out}. Record decisions in the file "
          "(status 'accepted' and a decision naming the option), then run repair-apply.",
          file=sys.stderr)
    return 0


def cmd_repair_apply(args):
    """Apply the decisions recorded in a plan file. The CLI applies nothing the file
    does not record as accepted; it does not check REPAIR_ALLOWED_USERS."""
    import shutil
    import tempfile
    from .release_repair.apply import ApplyError, apply_plan
    from .release_repair.model import Plan
    from .release_repair.planner import DecisionError, fill_ops
    with open(args.plan, encoding="utf-8") as fh:
        plan = Plan.from_dict(json.load(fh))
    for r in plan.remedies:
        if r.status == "accepted" and r.decision and not r.decision.get("ops"):
            opt = r.option(r.decision.get("option") or "")
            if opt is None:
                print(f"{r.id}: the decision names no option", file=sys.stderr)
                return errors.EXIT_FAIL
            try:
                r.decision["ops"] = fill_ops(opt, r.decision.get("content"),
                                             [tuple(x) for x in plan.prefixes])
            except DecisionError as e:
                print(f"{r.id}: {e}", file=sys.stderr)
                return errors.EXIT_FAIL
    release = args.release if len(args.release) > 1 else args.release[0]
    work = tempfile.mkdtemp(prefix="owltester-repair-")
    try:
        result = apply_plan(plan, release, work, reaudit=not args.no_audit,
                            progress=lambda s: print(s, file=sys.stderr))
        out = os.path.join(work, "out")
        shutil.copyfile(os.path.join(out, result["outputs"]["zip"]), args.out)
        if args.outputs:
            shutil.copytree(out, args.outputs, dirs_exist_ok=True)
    except ApplyError as e:
        print(f"apply failed ({e.code}): {e}", file=sys.stderr)
        return errors.EXIT_FAIL
    finally:
        shutil.rmtree(work, ignore_errors=True)
    summary = {k: result.get(k) for k in ("applied", "verdict_before", "verdict_after", "fixed")}
    print(json.dumps(summary, indent=1))
    return errors.EXIT_PASS if result.get("fixed", True) else errors.EXIT_FAIL


def cmd_serve(args):
    from flask import Flask
    from .service import bp, configure
    from .audit_service import audit_pages_bp
    from . import repair_service  # noqa: F401 - adds the repair routes to both blueprints
    configure(kernel_path=args.kernel)
    app = Flask("owltester")
    app.secret_key = os.environ.get("SESSION_SECRET") or os.urandom(32)
    app.register_blueprint(bp)
    app.register_blueprint(audit_pages_bp)
    app.run(host=args.host, port=args.port)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="owltester", description="SOoL OWL gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="validate an artifact (exit 0 pass / non-zero fail)")
    pc.add_argument("artifact")
    pc.add_argument("--kernel", default=default_kernel_path())
    pc.add_argument("--all", action="store_true", help="run all stages, don't stop at first failure")
    pc.add_argument("--baseline", help="input artifact to activate Stage E delta checks")
    pc.add_argument("--json", help="write the JSON report to this path")
    pc.set_defaults(func=cmd_check)

    pr = sub.add_parser("repair", help="conservative, logged repair")
    pr.add_argument("artifact")
    pr.add_argument("--kernel", default=default_kernel_path())
    pr.add_argument("--out", help="path for the repaired artifact")
    pr.add_argument("--quarantine", help="path for the quarantine log")
    pr.add_argument("--max-removed", type=float, default=0.02, dest="max_removed")
    pr.set_defaults(func=cmd_repair)

    pa = sub.add_parser("audit", help="full audit of a released artifact "
                                      "(exit 0 on pass or warn, 1 on fail)")
    pa.add_argument("artifact", nargs="+", help="a zip, a directory, or several files")
    pa.add_argument("--profile", default="general", choices=("general", "bfo", "sool"))
    pa.add_argument("--json", help="write the JSON report here")
    pa.add_argument("--html", help="write the HTML report here")
    pa.add_argument("--md", help="write the Markdown report here")
    pa.add_argument("--budget", type=float, default=None, help="total seconds (default 900)")
    pa.add_argument("--max-explanations", type=int, default=None, dest="max_explanations",
                    help="inconsistent files to explain (default 3)")
    pa.add_argument("--no-explain", action="store_true", dest="no_explain",
                    help="skip minimal-cause search for inconsistent files")
    pa.add_argument("--config", help="audit.yaml or audit.json (default: the one at the archive root)")
    pa.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    pa.add_argument("--fail-on", default="critical", choices=("critical", "major", "minor"),
                    dest="fail_on", help="exit 1 when a finding not declared expected is at or "
                                         "above this severity (default critical)")
    pa.add_argument("--summary-md", dest="summary_md",
                    help="write a short Markdown summary (for a CI job summary or PR comment)")
    pa.set_defaults(func=cmd_audit)

    rp = sub.add_parser("repair-plan", help="build a guided repair plan from an audit report")
    rp.add_argument("report", help="the audit's JSON report (owltester audit --json)")
    rp.add_argument("--release", nargs="+", required=True, help="the zip, directory or files audited")
    rp.add_argument("--out", required=True, help="where to write plan.json")
    rp.set_defaults(func=cmd_repair_plan)

    ra = sub.add_parser("repair-apply", help="apply the accepted decisions in a plan file")
    ra.add_argument("plan")
    ra.add_argument("--release", nargs="+", required=True)
    ra.add_argument("--out", required=True, help="where to write the repaired zip")
    ra.add_argument("--outputs", help="directory for FIXLOG, repair.patch and the two audits")
    ra.add_argument("--no-audit", action="store_true", dest="no_audit",
                    help="skip the second audit (the result is then unverified)")
    ra.set_defaults(func=cmd_repair_apply)

    rc = sub.add_parser("record", help="write the verification record into a release directory")
    rc.add_argument("release", help="the release directory (the files to ship)")
    rc.add_argument("--report", required=True, help="the audit's JSON report (owltester audit --json)")
    rc.add_argument("--out", help="VERIFICATION.json at the release root (the default)")
    rc.add_argument("--commit")
    rc.add_argument("--tag")
    rc.add_argument("--repository", help="for example https://github.com/<owner>/<repo>")
    rc.add_argument("--name")
    rc.add_argument("--version")
    rc.add_argument("--fail-on", default="critical", choices=("critical", "major", "minor"), dest="fail_on")
    rc.add_argument("--attest", action="store_true",
                    help="the CI signs the record with a GitHub artifact attestation")
    rc.set_defaults(func=cmd_record)

    rv = sub.add_parser("verify", help="check a release against its verification record")
    rv.add_argument("release", help="the release zip or directory")
    rv.add_argument("--reaudit", action="store_true", help="also audit again and compare")
    rv.add_argument("--allow", action="append", help="glob of extra files to accept (repeatable)")
    rv.add_argument("--json", help="write the result as JSON")
    rv.set_defaults(func=cmd_verify)

    pb = sub.add_parser("build", help="build an audited release from one OWL file")
    pb.add_argument("input", help="the ontology file (any format OwlTester reads)")
    pb.add_argument("--answers", required=True, help="build.yaml with the builder's answers")
    pb.add_argument("--out", required=True, help="output directory (dist/)")
    pb.add_argument("--import", action="append", dest="imports", default=[],
                    help="a file to resolve an owl:imports with (repeatable)")
    pb.add_argument("--shapes", action="append", default=[], help="SHACL shapes to include")
    pb.add_argument("--vocab", action="append", default=[], help="controlled vocabularies to include")
    pb.add_argument("--examples", action="append", default=[], help="example data to include")
    pb.add_argument("--previous", help="the previous release zip (version suggestion, CHANGELOG)")
    pb.add_argument("--no-audit", action="store_true", dest="no_audit")
    pb.add_argument("--quiet", action="store_true")
    pb.set_defaults(func=cmd_build)

    ps = sub.add_parser("serve", help="run the HTTP service")
    ps.add_argument("--host", default="0.0.0.0")
    ps.add_argument("--port", type=int, default=8080)
    ps.add_argument("--kernel", default=default_kernel_path())
    ps.set_defaults(func=cmd_serve)
    return p


class ToolInputError(Exception):
    """Unreadable or missing input: exit 2."""


EXIT_TOOL = 2


def main(argv=None):
    args = build_parser().parse_args(argv)      # argparse itself exits 2 on usage errors
    from .audit.files import ArtifactError
    from .release.tools import ToolError
    try:
        return args.func(args)
    except (ToolError, ToolInputError, ArtifactError, FileNotFoundError, IsADirectoryError,
            PermissionError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"owltester {args.cmd if hasattr(args, 'cmd') else ''}: error: {e}".replace("  ", " "),
              file=sys.stderr)
        return EXIT_TOOL


if __name__ == "__main__":
    sys.exit(main())
