"""CLI gate — section 8 of the spec.

    owltester check  <artifact> --kernel sool-kernel.ttl [--all] [--json report.json]
    owltester repair <artifact> --kernel ... --out repaired.ttl --quarantine q.ttl
    owltester serve  --port 8080 --kernel ...

Exit 0 == pass, non-zero == fail. The non-zero exit on a hollowed-out artifact is
the whole point: CI and the corpus export pipeline abort before any FTP upload.
"""

import argparse
import json
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


def cmd_serve(args):
    from flask import Flask
    from .service import bp, configure
    configure(kernel_path=args.kernel)
    app = Flask("owltester")
    app.register_blueprint(bp)
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
