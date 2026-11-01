"""The audit as a gate (SPEC-release.md, sections 1 and 6).

``--fail-on`` rejects a release when any finding not declared expected is at or
above the threshold. ``critical`` is the audit's old behaviour (exit 1 only on
``fail``); a release gate usually uses ``major``.
"""

SEVERITIES = ("critical", "major", "minor", "info")
FAIL_ON = ("critical", "major", "minor")


def blocking(report, fail_on="critical"):
    """The findings that make the gate reject ``report`` (an AuditReport dict)."""
    if fail_on not in FAIL_ON:
        raise ValueError(f"fail-on must be one of {', '.join(FAIL_ON)}")
    limit = SEVERITIES.index(fail_on)
    return [f for f in report.get("findings", [])
            if not f.get("expected") and f.get("severity") in SEVERITIES
            and SEVERITIES.index(f["severity"]) <= limit]


def rejected(report, fail_on="critical"):
    return bool(blocking(report, fail_on))


def counts(report):
    c = {s: 0 for s in SEVERITIES}
    c.update(report.get("severity_counts") or {})
    c.setdefault("expected", 0)
    return c


def counts_line(report):
    c = counts(report)
    line = f"{c['critical']} critical, {c['major']} major, {c['minor']} minor, {c['info']} info"
    if c["expected"]:
        line += f"; {c['expected']} expected outcome(s) declared"
    return line


def _cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def summary_md(report, fail_on="critical", top=10):
    """A short Markdown summary sized for a CI job summary or a PR comment."""
    stop = blocking(report, fail_on)
    gate = (f"**Gate (`--fail-on {fail_on}`): rejected**, {len(stop)} finding(s) at or above {fail_on}."
            if stop else f"**Gate (`--fail-on {fail_on}`): passed.**")
    lines = [f"## OwlTester audit: {report.get('verdict', '?')}", "",
             f"`{report.get('artifact', '')}`, {report.get('profile', 'general')} profile, "
             f"OwlTester `{report.get('tool_version', '')}`, {report.get('audited_at', '')}", "",
             f"{counts_line(report)}.", "", gate, "",
             "| Stage | Check | Status | Findings |", "| --- | --- | --- | --- |"]
    for row in report.get("scorecard", []):
        lines.append(f"| {row['stage']} | {_cell(row.get('check'))} | {_cell(row.get('status'))} | "
                     f"{row.get('findings', 0)} |")
    shown = [f for f in report.get("findings", []) if not f.get("expected")][:top]
    if shown:
        lines += ["", "**Top findings**", ""]
        for f in shown:
            where = ", ".join(f"`{p}`" for p in (f.get("files") or [])[:2])
            lines.append(f"- **{f['severity']}** `{f['code']}` {_cell(f.get('title'))}"
                         + (f" ({where})" if where else ""))
        rest = sum(1 for f in report.get("findings", []) if not f.get("expected")) - len(shown)
        if rest > 0:
            lines.append(f"- and {rest} more in the full report")
    return "\n".join(lines) + "\n"


def badge(report):
    """The shields.io endpoint JSON for a README badge (no server needed)."""
    verdict = report.get("verdict", "unknown")
    color = {"pass": "green", "warn": "yellow", "fail": "red"}.get(verdict, "lightgrey")
    return {"schemaVersion": 1, "label": "OwlTester", "message": verdict, "color": color}
