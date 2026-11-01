"""The verification record (SPEC-release.md, section 2) and ``verify``.

``VERIFICATION.json`` and ``VERIFICATION.md`` sit at the root of an audited
release. The record names the source (tag, commit), the tools, the audit's
verdict and counts, the expected outcomes, and the SHA-256 of every file. The
audit report ships inside the release as ``audit/report.json`` and ``.md``.

``verify`` checks a release against its record: every listed file present and
unchanged, nothing unlisted, the record's own digests intact, and with
``reaudit`` that a fresh audit gives the same verdict and finding codes.
"""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile

from . import gate

RECORD_VERSION = "1"
RECORD_JSON = "VERIFICATION.json"
RECORD_MD = "VERIFICATION.md"
BUNDLE = "VERIFICATION.sigstore.json"
REPORT_JSON = "audit/report.json"
REPORT_MD = "audit/report.md"
BADGE = "audit-badge.json"
# Never listed in ``files`` (they describe the files), never audited.
RECORD_FILES = (RECORD_JSON, RECORD_MD, BUNDLE)
# What the audit skips (owltester/audit/artifact.py NOT_AUDITED), so an audit of a
# recorded release matches the recorded audit.
NOT_AUDITED = RECORD_FILES + (REPORT_JSON, REPORT_MD, BADGE)
# Never part of a release, even when the release directory is a checkout.
SKIP_DIRS = (".git", "__pycache__", "node_modules")   # as the audit walks
CONFIG_NAMES = ("audit.yaml", "audit.yml", "audit.json")
# Findings the presence of the record itself adds on a re-audit.
REAUDIT_IGNORED = ("I_VERIFIED",)


class RecordError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_digest(record):
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(canonical(body)).hexdigest()


def list_files(root):
    """Every file under ``root`` as (relative posix path, absolute path), sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            ab = os.path.join(dirpath, name)
            if os.path.islink(ab):
                continue
            rel = os.path.relpath(ab, root).replace(os.sep, "/")
            out.append((rel, ab))
    return sorted(out)


def file_entries(root):
    return [{"path": rel, "sha256": sha256_file(ab), "bytes": os.path.getsize(ab)}
            for rel, ab in list_files(root) if rel not in RECORD_FILES]


def _config_path(root):
    return next((os.path.join(root, n) for n in CONFIG_NAMES if os.path.isfile(os.path.join(root, n))), None)


def _header(root):
    """Ontology IRI, version IRI and version from the first ontology header found."""
    from rdflib import OWL, RDF, URIRef
    from ..audit.artifact import load_artifact
    try:
        art = load_artifact(root)
    except Exception:  # noqa: BLE001 - the record still names what it can
        return {}
    try:
        named = set(art.config.get("ontology") or [])
        files = sorted(art.by_role("ontology"), key=lambda f: (f.path not in named, "-base." in f.path, f.path))
        for f in files:
            g = f.graph
            h = next((s for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
            if h is not None:
                vi, info = g.value(h, OWL.versionIRI), g.value(h, OWL.versionInfo)
                return {"ontology_iri": str(h), "version_iri": str(vi) if vi else None,
                        "version": str(info) if info else None}
    finally:
        art.cleanup()
    return {}


def expected_outcomes(report):
    return [{"code": f["code"], "file": (f.get("files") or [None])[0], "reason": f["expected"]}
            for f in report.get("findings", []) if f.get("expected")]


def write_report(root, report):
    """Ship the audit report inside the release."""
    from ..audit.render import to_markdown
    from ..model import AuditReport
    os.makedirs(os.path.join(root, "audit"), exist_ok=True)
    with open(os.path.join(root, REPORT_JSON), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(root, REPORT_MD), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_markdown(AuditReport.from_dict(report)))


def make_record(root, report, *, name=None, version=None, tag=None, commit=None, repository=None,
                fail_on="critical", attest=False, tool=None):
    """Write the report into ``root`` and return the record (not yet written)."""
    from .tools import versions
    write_report(root, report)
    head = _header(root)
    version = version or (tag[1:] if tag and tag[:1] in "vV" else tag) or head.get("version")
    cfg = _config_path(root)
    record = {
        "record_version": RECORD_VERSION,
        "release": {"name": name or report.get("artifact") or os.path.basename(os.path.abspath(root)),
                    "version": version, "tag": tag, "commit": commit, "repository": repository,
                    "ontology_iri": head.get("ontology_iri"), "version_iri": head.get("version_iri")},
        "tool": tool if tool is not None else versions(report.get("tool_version")),
        "audit": {"profile": report.get("profile"),
                  "config": os.path.basename(cfg) if cfg else None,
                  "config_sha256": sha256_file(cfg) if cfg else None,
                  "verdict": report.get("verdict"), "fail_on": fail_on,
                  "gate": "rejected" if gate.rejected(report, fail_on) else "passed",
                  "severity_counts": gate.counts(report),
                  "expected": expected_outcomes(report),
                  "report": REPORT_JSON,
                  "report_sha256": sha256_file(os.path.join(root, REPORT_JSON)),
                  "audited_at": report.get("audited_at")},
        "files": file_entries(root),
        "attestation": ({"kind": "github-artifact-attestation", "bundle": BUNDLE} if attest else None),
    }
    record["record_sha256"] = record_digest(record)
    return record


def record_md(record):
    a, r, t = record["audit"], record["release"], record["tool"]
    c = a["severity_counts"]
    date = (a.get("audited_at") or "")[:10]
    expected = f"; {c.get('expected', 0)} expected outcomes declared in {a.get('config') or 'audit.yaml'}" \
        if c.get("expected") else ""
    lines = [f"Audited by OwlTester `{t.get('owltester')}` on `{date}`: {a['verdict']} "
             f"({c['critical']} critical, {c['major']} major, {c['minor']} minor{expected}).", "",
             f"# Verification record: {r.get('name')} {r.get('version') or ''}".rstrip(), ""]
    signed = record.get("attestation")
    lines.append("Signed with a GitHub artifact attestation (`gh attestation verify VERIFICATION.json "
                 f"--repo <owner/repo>`; bundle `{signed['bundle']}`)." if signed else
                 "This record is not signed. Its checksums show the files are the ones audited; "
                 "they do not show who produced them.")
    lines += ["", "| Release | |", "| --- | --- |"]
    for k in ("name", "version", "tag", "commit", "repository", "ontology_iri", "version_iri"):
        if r.get(k):
            lines.append(f"| {k.replace('_', ' ')} | `{r[k]}` |")
    lines += ["", "| Tool | Version |", "| --- | --- |"]
    lines += [f"| {k} | `{v}` |" for k, v in sorted(t.items()) if v]
    lines += ["", f"Gate: `--fail-on {a['fail_on']}` {a['gate']}. Profile `{a.get('profile')}`."
              + (f" Configuration `{a['config']}` (sha256 `{a['config_sha256']}`)." if a.get("config") else ""),
              f"Full report: `{a['report']}` (sha256 `{a['report_sha256']}`)."]
    if a.get("expected"):
        lines += ["", "## Expected outcomes", "", "| Code | File | Reason |", "| --- | --- | --- |"]
        lines += [f"| `{e['code']}` | `{e.get('file') or ''}` | {gate._cell(e.get('reason'))} |"
                  for e in a["expected"]]
    lines += ["", "## Files", "", "| File | Bytes | SHA-256 |", "| --- | ---: | --- |"]
    lines += [f"| `{f['path']}` | {f['bytes']} | `{f['sha256']}` |" for f in record["files"]]
    lines += ["", f"Record digest: `{record['record_sha256']}`. Check it all with "
                  "`owltester verify <release> [--reaudit]`.", ""]
    return "\n".join(lines)


def write_record(root, record):
    with open(os.path.join(root, RECORD_JSON), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(root, RECORD_MD), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(record_md(record))


# -- verify ----------------------------------------------------------------------------------

def open_release(source):
    """(root, cleanup) for a release directory or zip (a single top folder is stripped)."""
    if os.path.isdir(source):
        return os.path.abspath(source), (lambda: None)
    if not zipfile.is_zipfile(source):
        raise RecordError(f"{source} is neither a directory nor a zip")
    from ..audit.files import extract_zip
    work = tempfile.mkdtemp(prefix="owltester-verify-")
    root = os.path.join(work, "release")
    os.makedirs(root)
    extract_zip(source, root)          # strips a single top folder itself
    return root, (lambda: shutil.rmtree(work, ignore_errors=True))


def check_files(root, record, allow=()):
    """Problems with the files against the record (no audit)."""
    import fnmatch
    problems = []
    if record.get("record_sha256") != record_digest(record):
        problems.append(f"{RECORD_JSON} was edited: its digest does not match its content")
    listed = {f["path"]: f for f in record.get("files", [])}
    present = {rel: ab for rel, ab in list_files(root) if rel not in RECORD_FILES}
    for path, f in sorted(listed.items()):
        ab = present.get(path)
        if ab is None:
            problems.append(f"missing: {path}")
        elif os.path.getsize(ab) != f.get("bytes") or sha256_file(ab) != f.get("sha256"):
            problems.append(f"altered: {path}")
    for path in sorted(set(present) - set(listed)):
        if not any(fnmatch.fnmatch(path, pat) for pat in allow):
            problems.append(f"not in the record: {path}")
    a = record.get("audit") or {}
    rep = present.get(a.get("report") or REPORT_JSON)
    if rep is not None and a.get("report_sha256") and sha256_file(rep) != a["report_sha256"]:
        problems.append(f"altered: {a.get('report') or REPORT_JSON} (report_sha256)")
    cfg = present.get(a.get("config") or "")
    if a.get("config") and (cfg is None or sha256_file(cfg) != a.get("config_sha256")):
        problems.append(f"altered: {a['config']} (config_sha256)")
    md = os.path.join(root, RECORD_MD)
    if os.path.isfile(md):
        with open(md, encoding="utf-8") as fh:
            if fh.read() != record_md(record):
                problems.append(f"{RECORD_MD} does not match {RECORD_JSON}")
    if rep is not None and not problems:
        with open(rep, encoding="utf-8") as fh:
            report = json.load(fh)
        if report.get("verdict") != a.get("verdict") or gate.counts(report) != a.get("severity_counts"):
            problems.append(f"{RECORD_JSON} and {a.get('report') or REPORT_JSON} disagree on the verdict or counts")
    return problems


def load_record(root):
    path = os.path.join(root, RECORD_JSON)
    if not os.path.isfile(path):
        raise RecordError(f"no {RECORD_JSON} at the root of the release")
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except ValueError as e:
        raise RecordError(f"{RECORD_JSON} is not valid JSON: {e}") from e
    if str(record.get("record_version")) != RECORD_VERSION:
        raise RecordError(f"{RECORD_JSON}: unknown record_version {record.get('record_version')!r}")
    return record


def _codes(report):
    return sorted({f["code"] for f in report.get("findings", []) if f["code"] not in REAUDIT_IGNORED})


def verify(source, reaudit=False, allow=(), budget=None):
    """{"ok", "problems", "record", "reaudit"} for a release directory or zip."""
    root, cleanup = open_release(source)
    try:
        record = load_record(root)
        problems = check_files(root, record, allow)
        result = {"ok": not problems, "problems": problems, "record": record, "reaudit": None}
        if reaudit:
            from ..audit.runner import run_audit
            a = record["audit"]
            with open(os.path.join(root, a.get("report") or REPORT_JSON), encoding="utf-8") as fh:
                recorded = json.load(fh)
            fresh = run_audit(root, profile=a.get("profile") or "general", budget=budget,
                              artifact_name=recorded.get("artifact")).to_dict()
            diff = {"verdict": [recorded.get("verdict"), fresh["verdict"]],
                    "only_recorded": sorted(set(_codes(recorded)) - set(_codes(fresh))),
                    "only_fresh": sorted(set(_codes(fresh)) - set(_codes(recorded)))}
            result["reaudit"] = {"verdict": fresh["verdict"], "codes": _codes(fresh), "diff": diff}
            if diff["verdict"][0] != diff["verdict"][1]:
                problems.append(f"re-audit verdict {fresh['verdict']}, recorded {recorded.get('verdict')}")
            if diff["only_recorded"]:
                problems.append("re-audit no longer finds: " + ", ".join(diff["only_recorded"]))
            if diff["only_fresh"]:
                problems.append("re-audit also finds: " + ", ".join(diff["only_fresh"]))
            result["ok"] = not problems
        return result
    finally:
        cleanup()
