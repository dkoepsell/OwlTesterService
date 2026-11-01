"""Entry point of the OwlTester GitHub Action (SPEC-release.md, section 4).

Runs inside the CLI image: ``python -m owltester.release.action``. Inputs come
as ``INPUT_*`` variables (set by action/action.yml). Everything for the runner
is written to ``$OWLTESTER_OUT`` (default ``owltester-report/``):

    report.json, report.md     the full report (uploaded as a workflow artifact)
    summary.md                 appended to the job summary
    outputs.env                key=value lines appended to $GITHUB_OUTPUT
    audit-badge.json           shields.io endpoint JSON, when ``badge`` is set

Exit 0 when the gate passes, 1 when ``fail-on`` rejects the release, 2 when the
tool cannot run. Posting the PR comment is the only network call, and only
when ``comment`` is true.
"""

import json
import os
import sys
import urllib.request

from . import gate, record

API = "https://api.github.com"


def _input(name, default=""):
    return os.environ.get(f"INPUT_{name.upper().replace('-', '_')}", default).strip() or default


def _true(name):
    return _input(name, "false").lower() in ("1", "true", "yes", "on")


def _comment(body):
    """Post ``body`` on the pull request this run is for. Returns a note for the log."""
    token = os.environ.get("GITHUB_TOKEN", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (token and event_path and repo and os.path.isfile(event_path)):
        return "comment skipped: needs GITHUB_TOKEN and a pull_request event"
    with open(event_path, encoding="utf-8") as fh:
        number = (json.load(fh).get("pull_request") or {}).get("number")
    if not number:
        return "comment skipped: this run is not for a pull request"
    req = urllib.request.Request(f"{API}/repos/{repo}/issues/{int(number)}/comments",
                                 data=json.dumps({"body": body}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "owltester-action"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return f"comment posted ({res.status})"
    except Exception as e:  # noqa: BLE001 - a failed comment must not fail the audit
        return f"comment failed: {e}"


def run(env=None):
    from ..audit.runner import run_audit
    from ..audit.render import to_markdown
    from ..model import AuditReport
    from .tools import ToolError, require_java
    if env:
        os.environ.update(env)
    out = os.path.abspath(os.environ.get("OWLTESTER_OUT", "owltester-report"))
    os.makedirs(out, exist_ok=True)
    path = _input("path", ".")
    fail_on = _input("fail-on", "major")
    profile = _input("profile", "general")
    config = _input("config", "")
    try:
        require_java()
        if fail_on not in gate.FAIL_ON:
            raise ToolError(f"fail-on must be one of {', '.join(gate.FAIL_ON)}")
        if not os.path.exists(path):
            raise ToolError(f"path {path} does not exist")
        if config and not os.path.isfile(config):
            raise ToolError(f"config {config} does not exist")
        budget = float(_input("budget", "900"))
        report = run_audit(path, profile=profile, config_path=config or None, budget=budget).to_dict()
    except (ToolError, ValueError, OSError) as e:
        print(f"::error title=OwlTester::{e}")
        return 2
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(to_markdown(AuditReport.from_dict(report)))
    summary = gate.summary_md(report, fail_on)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(summary)
    record_path = ""
    if _true("record"):
        if not os.path.isdir(path):
            print("::error title=OwlTester::record needs path to be the release directory, not a zip")
            return 2
        ref_type, ref = os.environ.get("GITHUB_REF_TYPE", ""), os.environ.get("GITHUB_REF_NAME", "")
        server, repo = os.environ.get("GITHUB_SERVER_URL", "https://github.com"), os.environ.get("GITHUB_REPOSITORY")
        r = record.make_record(path, report, tag=ref if ref_type == "tag" else None,
                               commit=os.environ.get("GITHUB_SHA") or None,
                               repository=f"{server}/{repo}" if repo else None,
                               fail_on=fail_on, attest=_true("attest"))
        record.write_record(path, r)
        record_path = os.path.join(path, record.RECORD_JSON)
    if _input("badge", ""):
        badge_path = _input("badge")
        os.makedirs(os.path.dirname(os.path.abspath(badge_path)) or ".", exist_ok=True)
        with open(badge_path, "w", encoding="utf-8") as fh:
            json.dump(gate.badge(report), fh)
    if _true("comment"):
        print(_comment(summary))
    c = gate.counts(report)
    with open(os.path.join(out, "outputs.env"), "w", encoding="utf-8") as fh:
        fh.write(f"verdict={report['verdict']}\n")
        fh.write(f"report-json={os.path.join(out, 'report.json')}\n")
        fh.write(f"report-md={os.path.join(out, 'report.md')}\n")
        fh.write(f"record={record_path}\n")
        fh.write(f"counts={json.dumps(c, sort_keys=True)}\n")
    stop = gate.blocking(report, fail_on)
    for f in stop[:20]:
        files = (f.get("files") or [""])[0]
        print(f"::error {'file=' + files + ',' if files else ''}title=OwlTester {f['code']}::{f['title']}")
    print(f"OwlTester: {report['verdict']} ({gate.counts_line(report)}); gate --fail-on {fail_on}: "
          f"{'rejected' if stop else 'passed'}")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(run())
