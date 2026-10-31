"""Report outputs: Markdown, a zip of one Markdown issue per finding, and HTML.

Text from the archive (literals, file names, IRIs) is data: the HTML template
autoescapes it, and Markdown output escapes table pipes and fences.
"""

import io
import json
import re
import zipfile

from ..model import STAGE_ORDER, AuditReport
from .lenses import confirmed_rows

VERDICT_WORDS = {"fail": "FAIL: at least one critical finding",
                 "warn": "WARN: no critical findings, at least one major finding",
                 "pass": "PASS: no critical or major findings"}


def _text(text):
    """Archive text in Markdown prose: no raw HTML when the report is pasted somewhere."""
    return str(text if text is not None else "").replace("<", "&lt;").replace(">", "&gt;")


def _cell(text):
    return _text(text).replace("|", "\\|").replace("\n", " ")


def _fence(text, lang=""):
    text = str(text)
    ticks = "````" if "```" in text else "```"
    return f"{ticks}{lang}\n{text.rstrip()}\n{ticks}"


def _evidence_md(ev):
    out = []
    for key, val in ev.items():
        label = key.replace("_", " ")
        if key == "minimal_triples":
            out.append(f"**Minimal inconsistent triples**\n\n{_fence(val, 'turtle')}")
        elif key == "example":
            out.append(f"**Example as published**\n\n{_fence(val, 'turtle')}")
        elif isinstance(val, (str, int, float, bool)) or val is None:
            out.append(f"- **{label}:** {_text(val)}")
        elif isinstance(val, list) and all(isinstance(x, (str, int, float)) for x in val):
            out.append(f"- **{label}:** " + ", ".join(f"`{x}`" for x in val[:30])
                       + (f" (and {len(val) - 30} more)" if len(val) > 30 else ""))
        else:
            out.append(f"**{label}**\n\n{_fence(json.dumps(val, indent=1, ensure_ascii=False)[:6000], 'json')}")
    return "\n".join(out)


def finding_md(f, heading="###"):
    lines = [f"{heading} [{f.severity}] {f.id} {f.code}: {_text(f.title)}", "", _text(f.message), ""]
    if f.files:
        shown = ", ".join(f"`{p}`" for p in f.files[:12])
        lines.append(f"- **Files ({len(f.files)}):** {shown}" + (" ..." if len(f.files) > 12 else ""))
    if f.count > 1:
        lines.append(f"- **Occurrences:** {f.count:,}")
    if f.iri:
        lines.append(f"- **IRI:** <{f.iri}>")
    if f.related:
        lines.append(f"- **Explained by:** {', '.join(f.related)}")
    if f.fix:
        lines.append(f"- **Fix:** {_text(f.fix)}")
    if f.evidence:
        lines += ["", "<details><summary>Evidence</summary>", "", _evidence_md(f.evidence), "",
                  "</details>"]
    return "\n".join(lines) + "\n"


def to_markdown(report: AuditReport):
    counts = report.severity_counts()
    out = [f"# Audit report: {report.artifact}", "",
           f"**Verdict:** {VERDICT_WORDS[report.verdict]}  ",
           f"**Findings:** {counts['critical']} critical, {counts['major']} major, "
           f"{counts['minor']} minor, {counts['info']} info  ",
           f"**Profile:** {report.profile} | **Audited:** {report.audited_at} | "
           f"**Tool version:** {report.tool_version}", "",
           "## Scorecard", "", "| Stage | Check | Status | Worst | Findings | Summary |",
           "| --- | --- | --- | --- | --- | --- |"]
    for row in report.scorecard():
        out.append("| " + " | ".join(_cell(row[k]) for k in
                                        ("stage", "check", "status", "worst", "findings", "summary")) + " |")
    if report.patches:
        out += ["", "## Patches applied", ""]
        out += [f"- **{p['name']}:** {p['detail']}" for p in report.patches]
    if report.limits_hit:
        out += ["", "## Limits hit", ""]
        out += [f"- {lim['stage']} {lim['limit']}: {lim['detail']}" for lim in report.limits_hit]
    out += ["", "## Findings", ""]
    for stage in STAGE_ORDER:
        mine = [f for f in report.sorted_findings() if f.stage == stage]
        if not mine:
            continue
        title = report.stages.get(stage, {}).get("title", stage)
        out += [f"### {stage}: {title}", ""]
        out += [finding_md(f, "####") for f in mine]
    rows = confirmed_rows(report.lenses)
    if rows:
        out += ["## Conceptual review (confirmed by a reviewer)", "",
                "| Lens | Node | Question | Terms | Note |", "| --- | --- | --- | --- | --- |"]
        for lens, row in rows:
            terms = ", ".join(c["term"] for c in row["candidates"]) or "none"
            out.append(f"| {_cell(lens['title'])} | {_cell(row['node'])} | {_cell(row['question'])} "
                       f"| {_cell(terms)} | {_cell(row.get('note'))} |")
    out += ["", "## Manifest", "", _manifest_md(report.manifest)]
    return "\n".join(out) + "\n"


def _manifest_md(m):
    if not m:
        return "(none)"
    lines = [f"- **Files:** {m.get('files_total', 0)} ({m.get('rdf_files', 0)} RDF, "
             f"{m.get('triples', 0):,} triples)"]
    for role, paths in sorted(m.get("roles", {}).items()):
        lines.append(f"- **{role} ({len(paths)}):** " + ", ".join(f"`{p}`" for p in paths[:15])
                     + (" ..." if len(paths) > 15 else ""))
    for name, ds in m.get("data_sets", {}).items():
        lines.append(f"- **Data set `{name}`:** {ds['files']} files" + (" (legacy)" if ds["legacy"] else ""))
    lines.append("- **Owned namespaces:** " + ", ".join(f"`{n}`" for n in m.get("owned_namespaces", [])))
    unresolved = m.get("imports", {}).get("unresolved", [])
    if unresolved:
        lines.append("- **Imports not resolved locally:** " + ", ".join(f"`{i['iri']}`" for i in unresolved))
    return "\n".join(lines)


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60].lower()


def issues_zip(report: AuditReport, include=("critical", "major", "minor")):
    """A zip of one Markdown file per finding, ready to file on a tracker."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        index = [f"# Issues from the audit of {report.artifact}", ""]
        for f in report.sorted_findings():
            if f.severity not in include:
                continue
            name = f"{f.id}-{_slug(f.code + ' ' + f.title)}.md"
            body = (f"{finding_md(f, '#')}\n---\nFound by the OwlTester full artifact audit "
                    f"({report.profile} profile, {report.audited_at}, tool {report.tool_version}).\n")
            zf.writestr(name, body)
            index.append(f"- [{f.severity}] [{f.id} {f.title}]({name})")
        zf.writestr("README.md", "\n".join(index) + "\n")
    return buf.getvalue()


def html_context(report: AuditReport):
    """Everything templates/audit_report.html needs, already grouped."""
    by_stage = []
    for stage in STAGE_ORDER:
        mine = [f for f in report.sorted_findings() if f.stage == stage]
        st = report.stages.get(stage)
        if st is None and not mine:
            continue
        by_stage.append({"stage": stage, "info": st or {}, "findings": mine})
    return {"report": report, "verdict_words": VERDICT_WORDS[report.verdict],
            "counts": report.severity_counts(), "scorecard": report.scorecard(),
            "by_stage": by_stage, "manifest": report.manifest,
            "json_dumps": lambda v: json.dumps(v, indent=1, ensure_ascii=False)}


def to_html(report: AuditReport, standalone=True):
    """Render outside a request (CLI --html): a self-contained page."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import os
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates")
    env = Environment(loader=FileSystemLoader(os.path.abspath(root)),
                      autoescape=select_autoescape(["html"]))
    tpl = env.get_template("audit_report_body.html")
    body = tpl.render(job_id=None, **html_context(report))
    if not standalone:
        return body
    return ("<!DOCTYPE html><html lang=\"en\" data-bs-theme=\"dark\"><head><meta charset=\"utf-8\">"
            f"<title>Audit: {_html_escape(report.artifact)}</title>"
            "<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\">"
            "</head><body><div class=\"container my-4\">" + body + "</div></body></html>")


def _html_escape(s):
    from markupsafe import escape
    return str(escape(s))
