"""HTTP surface of the full artifact audit (SPEC-audit.md, section 5).

Routes on the ``owltester`` blueprint:

    POST /owltester/audit                       multipart zip or files -> 202 {job_id}
    GET  /owltester/audit/<job_id>              {status, stage, progress, report when done}
    GET  /owltester/audit/<job_id>/report.html  .../report.md  .../issues.zip
    POST /owltester/audit/<job_id>/lens         a reviewer's decision on one lens row
    POST /owltester/audit/<job_id>/lens/<lens>/draft   AI draft with the visitor's own key

and the page ``GET /audit/<job_id>`` (``audit_pages_bp``), which polls and then
renders the report. Audits are private: only a signed-in account named in
AUDIT_ALLOWED_USERS may run one, and an empty list means nobody may (it fails
closed). A job belongs to the account that started it and only that account
can see it; there are no anonymous or public audits.
"""

import os

from flask import (Blueprint, Response, abort, current_app, jsonify, redirect, render_template,
                   request, url_for)
from werkzeug.utils import secure_filename

from .audit import jobs
from .audit.profiles import PROFILES
from .model import AuditReport
from .service import bp

audit_pages_bp = Blueprint("audit_pages", __name__)

ALLOWED = {"zip", "ttl", "owl", "rdf", "xml", "n3", "nt", "nq", "trig", "jsonld", "ofn", "owx",
           "yaml", "yml", "json"}


def audit_mode():
    """Always "signed-in": public audits were removed (AUDIT_MODE is ignored)."""
    return "signed-in"


def allowed_users():
    """AUDIT_ALLOWED_USERS: comma-separated usernames or emails who may start an
    audit. Empty means nobody may."""
    raw = os.environ.get("AUDIT_ALLOWED_USERS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def may_start_audit():
    """True if the current visitor may start an audit (for the upload page and the route)."""
    allow = allowed_users()
    try:
        from flask_login import current_user
        signed_in = current_user.is_authenticated
    except Exception:  # noqa: BLE001 - served without flask-login
        current_user, signed_in = None, False
    return signed_in and bool({str(getattr(current_user, "username", "")).lower(),
                               str(getattr(current_user, "email", "")).lower()} & allow)


def _upload_dir():
    return os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))


def _user_id():
    try:
        from flask_login import current_user
        return current_user.id if current_user.is_authenticated else None
    except Exception:  # noqa: BLE001 - blueprint served without flask-login (owltester serve)
        return None


def _wants_html():
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "text/html" and not request.is_json


def _job_or_404(job_id):
    """The job's sidecar, if the visitor may see it."""
    data = jobs.read(_upload_dir(), job_id) if jobs.JOB_ID.match(job_id or "") else None
    if data is None:
        abort(404)
    owner = (data.get("owner") or {}).get("user_id")
    if owner is None or owner != _user_id():
        abort(404)
    return data


def _report_or_409(data):
    if data.get("status") != "done":
        abort(409, description="The audit has not finished.")
    return AuditReport.from_dict(data["report"])


@bp.route("/audit", methods=["POST"])
def audit_start():
    if _user_id() is None:
        if _wants_html():
            return redirect(url_for("login", next=request.path)) if "login" in current_app.view_functions \
                else abort(401)
        return jsonify({"error": "Sign in to run an audit."}), 401
    if not may_start_audit():
        return jsonify({"error": "Full audits are not open to this account yet."}), 403
    uploads = [f for f in request.files.getlist("files") or request.files.getlist("file")
               or list(request.files.values()) if f and f.filename]
    if not uploads:
        return jsonify({"error": "Upload a zip of the release, or its files."}), 400
    profile = (request.form.get("profile") or "general").lower()
    if profile not in PROFILES:
        return jsonify({"error": f"profile must be one of {', '.join(PROFILES)}"}), 400
    names = [secure_filename(f.filename) for f in uploads]
    bad = [n for n in names if not n or n.rsplit(".", 1)[-1].lower() not in ALLOWED]
    if bad:
        return jsonify({"error": f"Unsupported file: {bad[0] or 'unnamed'}"}), 400

    uid = _user_id()
    artifact = names[0].rsplit(".", 1)[0] if len(names) == 1 else f"{len(names)} files"
    job_id, d = jobs.create(_upload_dir(), {"user_id": uid}, artifact, profile)
    paths = []
    for f, name in zip(uploads, names):
        path = os.path.join(d, "input", name)
        f.save(path)
        paths.append(path)
    source = paths[0] if len(paths) == 1 and names[0].lower().endswith(".zip") else paths
    # Guided release repair needs the release the audit saw; keep it only for
    # an owner who may repair (REPAIR_ALLOWED_USERS, closed by default).
    from .release_repair.access import may_repair
    from .release_repair.storage import sha256_of
    keep = may_repair()
    jobs.update(_upload_dir(), job_id, release_files=names, release_sha256=sha256_of(paths))
    jobs.start(_upload_dir(), job_id, source, profile,
               {"artifact_name": artifact, "explain": request.form.get("explain", "1") != "0"},
               keep_release=keep)
    if _wants_html():
        return redirect(url_for("audit_pages.audit_page", job_id=job_id))
    return jsonify({"job_id": job_id, "status": "queued",
                    "status_url": url_for("owltester.audit_status", job_id=job_id),
                    "page_url": url_for("audit_pages.audit_page", job_id=job_id)}), 202


@bp.route("/audit/<job_id>", methods=["GET"])
def audit_status(job_id):
    data = _job_or_404(job_id)
    out = {k: data.get(k) for k in ("job_id", "status", "stage", "progress", "artifact",
                                     "profile", "started_at", "finished_at", "error")}
    if data.get("status") == "done":
        out["report"] = data["report"]
    return jsonify(out)


def _may_fix(data):
    """Show "Fix this release" only to an allowed owner. The repair routes check again."""
    from .release_repair.access import may_repair
    uid = _user_id()
    return uid is not None and may_repair() and (data.get("owner") or {}).get("user_id") == uid


@bp.route("/audit/<job_id>/report.html", methods=["GET"])
def audit_report_html(job_id):
    from .audit.render import html_context
    data = _job_or_404(job_id)
    report = _report_or_409(data)
    return render_template("audit_report.html", job_id=job_id, may_fix=_may_fix(data),
                           **html_context(report))


@bp.route("/audit/<job_id>/report.md", methods=["GET"])
def audit_report_md(job_id):
    from .audit.render import to_markdown
    report = _report_or_409(_job_or_404(job_id))
    return Response(to_markdown(report), mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="audit-{job_id[:8]}.md"'})


@bp.route("/audit/<job_id>/issues.zip", methods=["GET"])
def audit_issues_zip(job_id):
    from .audit.render import issues_zip
    report = _report_or_409(_job_or_404(job_id))
    return Response(issues_zip(report), mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="audit-{job_id[:8]}-issues.zip"'})


@bp.route("/audit/<job_id>/lens", methods=["POST"])
def audit_lens_review(job_id):
    from .audit.lenses import review
    data = _job_or_404(job_id)
    _report_or_409(data)
    body = request.get_json(silent=True) or {}
    try:
        row = review(data["report"]["lenses"], str(body.get("lens", "")), str(body.get("row", "")),
                     str(body.get("status", "")), str(body.get("note", "")))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e).strip("'\"")}), 400
    jobs.update(_upload_dir(), job_id, report=data["report"])
    return jsonify(row)


@bp.route("/audit/<job_id>/lens/<lens>/draft", methods=["POST"])
def audit_lens_draft(job_id, lens):
    from kindwork.module_routes import visitor_ai
    from .audit.lenses import ai_draft
    data = _job_or_404(job_id)
    _report_or_409(data)
    ai = visitor_ai()
    if ai is None:
        return jsonify({"error": "An AI draft uses only your own API key. Add one in settings, "
                                 "or send it in the X-AI-Key header."}), 400
    table = next((t for t in data["report"]["lenses"] if t.get("lens") == lens), None)
    if table is None:
        abort(404)
    try:
        ai_draft(table, ai)
    except Exception as e:  # noqa: BLE001 - provider errors are the visitor's to see
        return jsonify({"error": f"The AI draft failed: {str(e)[:300]}"}), 502
    jobs.update(_upload_dir(), job_id, report=data["report"])
    return jsonify(table)


@audit_pages_bp.route("/audit/<job_id>", methods=["GET"])
def audit_page(job_id):
    data = _job_or_404(job_id)
    if data.get("status") == "done":
        from .audit.render import html_context
        return render_template("audit_report.html", job_id=job_id, may_fix=_may_fix(data),
                               **html_context(AuditReport.from_dict(data["report"])))
    return render_template("audit_job.html", job=data, job_id=job_id)


@audit_pages_bp.route("/audit", methods=["GET"])
def audit_upload_page():
    return redirect(url_for("upload_owl") + "#audit") if "upload_owl" in current_app.view_functions \
        else render_template("audit_job.html", job=None, job_id=None)
