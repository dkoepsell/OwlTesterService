"""CLI gate — section 8 of the spec.

    owltester check  <artifact> --kernel sool-kernel.ttl [--all] [--json report.json]
    owltester repair <artifact> --kernel ... --out repaired.ttl --quarantine q.ttl
    owltester serve  --port 8080 --kernel ...
    owltester audit  <zip|dir|files...> [--profile general|bfo|sool] [--json f] [--html f] [--md f]

Exit 0 == pass, non-zero == fail (for audit: 0 on pass or warn, 1 on fail). The non-zero exit on a hollowed-out artifact is
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
    return errors.EXIT_FAIL if d["verdict"] == "fail" else errors.EXIT_PASS


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

    ps = sub.add_parser("serve", help="run the HTTP service")
    ps.add_argument("--host", default="0.0.0.0")
    ps.add_argument("--port", type=int, default=8080)
    ps.add_argument("--kernel", default=default_kernel_path())
    ps.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
