"""HTTP surface of guided release repair (SPEC-audit-repair.md, sections 1 and 8).

Pages (``audit_pages_bp``):
    GET  /audit/<job_id>/repair                 resume the latest plan, or offer to start one
    POST /audit/<job_id>/repair                 start a plan (owner only)
    GET  /audit/<job_id>/repair/<plan_id>       the plan page

JSON (``owltester`` blueprint), under /owltester/audit/<job_id>/repair/:
    POST release                                upload the release again, if it was not kept
    GET  <plan_id>                              the plan, the apply status and your role
    POST <plan_id>/remedy/<rid>                 decide: accept | skip | declare | reopen | revert
    POST <plan_id>/remedy/<rid>/comment         comment, or propose an option (reviewers)
    POST <plan_id>/remedy/<rid>/ai              an AI suggestion, with your own key
    POST <plan_id>/apply   GET <plan_id>/apply  run the apply job, read its status
    GET  <plan_id>/out/<name>                   outputs; <plan_id>/issues.zip
    POST <plan_id>/members  DELETE <plan_id>/members/<user_id>   share and unshare

Every route checks, in order: signed in; named in REPAIR_ALLOWED_USERS or a power user; owner of
the audit job (or, for a plan, a member of it). A failure returns 404 for plans
and jobs, so their existence is not revealed, and 403 for the start route.
"""

import json
import logging
import os
import threading
import time

from flask import Response, abort, current_app, jsonify, redirect, render_template, request, \
    send_from_directory, url_for

from .audit import jobs
from .audit_service import audit_pages_bp
from .release_repair import access, storage
from .release_repair.apply import ApplyError, apply_plan
from .release_repair.planner import DecisionError, build_plan, decide, now
from .service import bp

logger = logging.getLogger(__name__)
OUTPUTS = {"zip", "patch", "fixlog_json", "fixlog_md", "changelog", "audit_before", "audit_after"}


def _upload_dir():
    return os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))


def _me():
    uid, username, email = access.current()
    return {"user_id": uid, "name": username or email}


def _job_for_repair(job_id, start=False):
    """The job sidecar, after the three access checks of spec 1.1."""
    fail = 403 if start else 404
    uid, _, _ = access.current()
    if uid is None or not access.may_repair():
        abort(fail)
    data = jobs.read(_upload_dir(), job_id) if jobs.JOB_ID.match(job_id or "") else None
    if data is None:
        abort(404)
    return data, uid


def _owner_job(job_id, start=False):
    data, uid = _job_for_repair(job_id, start)
    if (data.get("owner") or {}).get("user_id") != uid:
        abort(403 if start else 404)
    return data


def _plan_for(job_id, plan_id, need="view"):
    data, uid = _job_for_repair(job_id)
    plan = storage.load(_upload_dir(), job_id, plan_id) if storage.PLAN_ID.match(plan_id or "") else None
    if plan is None or plan.job_id != job_id:
        abort(404)
    role = access.role(plan, data, uid)
    if role is None:
        abort(404)
    if not access.can(role, need):
        abort(403)
    return data, plan, role


def _save(plan):
    with storage.lock(storage.plan_dir(_upload_dir(), plan.job_id, plan.plan_id)):
        storage.save(_upload_dir(), plan)


# -- plans ---------------------------------------------------------------------------------

def _build_in_background(app, upload_dir, job, plan, release):
    last = [0.0]

    def progress(stage, done, total):
        # The stub plan.json carries the progress; written at most once a second.
        if time.monotonic() - last[0] < 1 and done not in (0, total):
            return
        last[0] = time.monotonic()
        plan.build = {"stage": stage, "done": done, "total": total, "updated_at": now()}
        storage.save(upload_dir, plan)

    def go():
        with app.app_context():
            try:
                built = build_plan(job["report"], release, job_id=job["job_id"],
                                   user=plan.created_by, plan_id=plan.plan_id, progress=progress)
                built.created_at, built.release_sha256 = plan.created_at, plan.release_sha256
                built.status, built.build = "ready", {}
                storage.save(upload_dir, built)
            except Exception as e:  # noqa: BLE001 - shown on the plan page
                logger.error("repair plan %s failed: %s", plan.plan_id, e)
                plan.status, plan.error = "error", f"{type(e).__name__}: {str(e)[:400]}"
                storage.save(upload_dir, plan)
    t = threading.Thread(target=go, name=f"repair-plan-{plan.plan_id[:8]}", daemon=True)
    t.start()
    return t


BUILD_STALE_SECONDS = 15 * 60


def _build_state(plan):
    """What the page shows while a plan builds; "stale" when the build stopped
    reporting (the worker restarted or the thread died)."""
    if plan.status != "building":
        return {"status": plan.status}
    b = dict(plan.build or {})
    import datetime
    last = b.get("updated_at") or plan.created_at
    try:
        age = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.datetime.fromisoformat(last).replace(tzinfo=datetime.timezone.utc)).total_seconds()
    except ValueError:
        age = 0
    b.update(status="stale" if age > BUILD_STALE_SECONDS else "building", started_at=plan.created_at)
    return b


@audit_pages_bp.route("/audit/<job_id>/repair", methods=["GET"])
def repair_home(job_id):
    data = _owner_job(job_id)
    plans = storage.list_plans(_upload_dir(), job_id)
    if plans and request.args.get("new") != "1":
        return redirect(url_for("audit_pages.repair_plan_page", job_id=job_id, plan_id=plans[-1].plan_id))
    return render_template("audit_repair_start.html", job=data, job_id=job_id,
                           has_release=storage.release_source(_upload_dir(), job_id, data) is not None,
                           plans=plans)


@audit_pages_bp.route("/audit/<job_id>/repair", methods=["POST"])
def repair_start(job_id):
    from .release_repair.model import Plan
    data = _owner_job(job_id, start=True)
    if data.get("status") != "done":
        abort(409, description="The audit has not finished.")
    release = storage.release_source(_upload_dir(), job_id, data)
    if release is None:
        return redirect(url_for("audit_pages.repair_home", job_id=job_id, new=1))
    storage.sweep(_upload_dir())
    me = _me()
    import uuid
    plan = Plan(plan_id=uuid.uuid4().hex, job_id=job_id, artifact=data.get("artifact", ""),
                profile=data.get("profile", "general"), created_at=now(), created_by=me,
                status="building", release_sha256=data.get("release_sha256", ""))
    storage.save(_upload_dir(), plan)
    _build_in_background(current_app._get_current_object(), _upload_dir(), data, plan, release)
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify({"plan_id": plan.plan_id, "status": "building"}), 202
    return redirect(url_for("audit_pages.repair_plan_page", job_id=job_id, plan_id=plan.plan_id))


@audit_pages_bp.route("/audit/<job_id>/repair/<plan_id>", methods=["GET"])
def repair_plan_page(job_id, plan_id):
    data, plan, role = _plan_for(job_id, plan_id)
    return render_template("audit_repair_plan.html", job=data, job_id=job_id, plan=plan, role=role,
                           me=_me(), build=_build_state(plan), apply=storage.read_apply(_upload_dir(), job_id, plan_id),
                           can={k: access.can(role, k) for k in access.CAN})


@bp.route("/audit/<job_id>/repair/release", methods=["POST"])
def repair_upload_release(job_id):
    """Upload the release again when the audit did not keep it. It must be the same release."""
    from werkzeug.utils import secure_filename
    data = _owner_job(job_id, start=True)
    uploads = [f for f in request.files.getlist("files") or list(request.files.values()) if f and f.filename]
    if not uploads:
        return jsonify({"error": "Upload the same zip or files the audit ran on."}), 400
    d = storage.release_dir(_upload_dir(), job_id)
    tmp = d + ".upload"
    os.makedirs(tmp, exist_ok=True)
    names, paths = [], []
    for f in uploads:
        name = secure_filename(f.filename)
        if not name:
            continue
        path = os.path.join(tmp, name)
        f.save(path)
        names.append(name)
        paths.append(path)
    want = data.get("release_sha256")
    if want and storage.sha256_of(paths) != want:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify({"error": "These files are not the release this audit ran on."}), 400
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    jobs.update(_upload_dir(), job_id, release_files=names)
    if request.accept_mimetypes.best == "text/html":
        return redirect(url_for("audit_pages.repair_home", job_id=job_id, new=1))
    return jsonify({"ok": True, "files": names})


@bp.route("/audit/<job_id>/repair/<plan_id>", methods=["GET"])
def repair_plan_json(job_id, plan_id):
    data, plan, role = _plan_for(job_id, plan_id)
    out = plan.to_dict()
    out.pop("audit_before", None)
    out.update(role=role, progress=plan.progress(), build=_build_state(plan),
               apply=storage.read_apply(_upload_dir(), job_id, plan_id))
    return jsonify(out)


@bp.route("/audit/<job_id>/repair/<plan_id>/remedy/<rid>", methods=["POST"])
def repair_decide(job_id, plan_id, rid):
    data, plan, role = _plan_for(job_id, plan_id, need="decide")
    body = request.get_json(silent=True) or {}
    action = str(body.get("action", ""))
    release = None
    r = plan.remedy(rid)
    if r is not None and action == "accept":
        opt = r.option(str(body.get("option", "")))
        if opt is not None and (opt.input or {}).get("validate"):
            release = storage.release_source(_upload_dir(), job_id, data)
    with storage.lock(storage.plan_dir(_upload_dir(), job_id, plan_id)):
        plan = storage.load(_upload_dir(), job_id, plan_id)
        try:
            r = decide(plan, rid, action, option=body.get("option"), content=body.get("content"),
                       note=body.get("note", ""), user=_me(), ai_assisted=bool(body.get("ai_assisted")),
                       release=release)
        except DecisionError as e:
            return jsonify({"error": str(e)}), 400
        storage.save(_upload_dir(), plan)
    return jsonify({"remedy": r.to_dict(), "progress": plan.progress()})


@bp.route("/audit/<job_id>/repair/<plan_id>/remedy/<rid>/comment", methods=["POST"])
def repair_comment(job_id, plan_id, rid):
    data, plan, role = _plan_for(job_id, plan_id, need="comment")
    body = request.get_json(silent=True) or {}
    text = " ".join(str(body.get("text", "")).split())[:4000]
    propose = str(body.get("propose_option") or "") or None
    with storage.lock(storage.plan_dir(_upload_dir(), job_id, plan_id)):
        plan = storage.load(_upload_dir(), job_id, plan_id)
        r = plan.remedy(rid)
        if r is None:
            abort(404)
        if propose and r.option(propose) is None:
            return jsonify({"error": "no such option"}), 400
        if not text and not propose:
            return jsonify({"error": "write a comment or choose an option to propose"}), 400
        c = {"by": _me(), "role": role, "at": now(), "text": text, "propose_option": propose}
        r.comments.append(c)
        storage.save(_upload_dir(), plan)
    return jsonify(c)


@bp.route("/audit/<job_id>/repair/<plan_id>/remedy/<rid>/ai", methods=["POST"])
def repair_ai(job_id, plan_id, rid):
    from kindwork.module_routes import visitor_ai
    from .release_repair.ai import suggest
    data, plan, role = _plan_for(job_id, plan_id, need="decide")
    r = plan.remedy(rid)
    opt = r.option(str((request.get_json(silent=True) or {}).get("option", ""))) if r else None
    if opt is None:
        abort(404)
    ai = visitor_ai()
    if ai is None:
        return jsonify({"error": "AI suggestions use only your own API key. Add one in settings, "
                                 "or send it in the X-AI-Key header."}), 400
    try:
        out = suggest(r, opt, ai)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001 - provider errors are the visitor's to see
        return jsonify({"error": f"The AI suggestion failed: {str(e)[:300]}"}), 502
    return jsonify(dict(out, ai_assisted=True))


# -- apply -------------------------------------------------------------------------------

def _apply_in_background(app, upload_dir, job_id, plan_id, release, user):
    # Written before the thread starts, so a poll right after the 202 sees "running".
    state = {"status": "running", "started_at": now(), "stage": "", "by": user}
    storage.write_apply(upload_dir, job_id, plan_id, state)

    def go():
        def progress(stage):
            state.update(stage=stage)
            storage.write_apply(upload_dir, job_id, plan_id, state)
        with app.app_context():
            try:
                plan = storage.load(upload_dir, job_id, plan_id)
                result = apply_plan(plan, release, storage.plan_dir(upload_dir, job_id, plan_id),
                                    progress=progress)
                with storage.lock(storage.plan_dir(upload_dir, job_id, plan_id)):
                    plan = storage.load(upload_dir, job_id, plan_id)
                    for r in plan.remedies:
                        if r.id in result["applied"]:
                            r.status = "applied"
                        elif r.status == "applied":
                            r.status = "reverted"
                    plan.apply = {"finished_at": now(), "fixed": result.get("fixed"),
                                  "applied": result["applied"]}
                    storage.save(upload_dir, plan)
                state.update(status="done", stage="", finished_at=now(), result=result)
            except ApplyError as e:
                state.update(status="error", error=str(e), code=e.code, finished_at=now())
            except Exception as e:  # noqa: BLE001 - the thread must never die silently
                logger.error("repair apply %s failed: %s", plan_id, e)
                state.update(status="error", error=f"{type(e).__name__}: {str(e)[:500]}", finished_at=now())
            storage.write_apply(upload_dir, job_id, plan_id, state)
    t = threading.Thread(target=go, name=f"repair-apply-{plan_id[:8]}", daemon=True)
    t.start()
    return t


@bp.route("/audit/<job_id>/repair/<plan_id>/apply", methods=["POST"])
def repair_apply(job_id, plan_id):
    data, plan, role = _plan_for(job_id, plan_id, need="apply")
    if plan.status != "ready":
        return jsonify({"error": "The plan is not ready."}), 409
    if storage.read_apply(_upload_dir(), job_id, plan_id).get("status") == "running":
        return jsonify({"error": "An apply is already running."}), 409
    release = storage.release_source(_upload_dir(), job_id, data)
    if release is None:
        return jsonify({"error": "The release is no longer stored; upload it again."}), 409
    storage.sweep(_upload_dir())
    _apply_in_background(current_app._get_current_object(), _upload_dir(), job_id, plan_id, release, _me())
    return jsonify({"status": "running"}), 202


@bp.route("/audit/<job_id>/repair/<plan_id>/apply", methods=["GET"])
def repair_apply_status(job_id, plan_id):
    _plan_for(job_id, plan_id)
    return jsonify(storage.read_apply(_upload_dir(), job_id, plan_id))


@bp.route("/audit/<job_id>/repair/<plan_id>/out/<name>", methods=["GET"])
def repair_output(job_id, plan_id, name):
    _plan_for(job_id, plan_id, need="export")
    state = storage.read_apply(_upload_dir(), job_id, plan_id)
    outputs = (state.get("result") or {}).get("outputs") or {}
    if name not in OUTPUTS or name not in outputs:
        abort(404)
    out_dir = os.path.join(storage.plan_dir(_upload_dir(), job_id, plan_id), "out")
    return send_from_directory(out_dir, outputs[name], as_attachment=name in ("zip", "patch"))


@bp.route("/audit/<job_id>/repair/<plan_id>/issues.zip", methods=["GET"])
def repair_issues(job_id, plan_id):
    from .audit.render import issues_zip
    from .model import AuditReport
    data, plan, role = _plan_for(job_id, plan_id, need="export")
    patches = {}
    path = os.path.join(storage.plan_dir(_upload_dir(), job_id, plan_id), "out", "patches.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            patches = json.load(fh)
    fixes = {}
    for r in plan.remedies:
        d = r.decision or {}
        opt = r.option(d.get("option") or "")
        if r.status in ("accepted", "applied") and opt is not None:
            fixes[r.finding_id] = {"summary": f"{opt.label}. {opt.consequence}", "patch": patches.get(r.id, "")}
        elif r.options and r.status == "open":
            best = next((o for o in r.options if o.recommended), r.options[0])
            fixes[r.finding_id] = {"summary": f"Suggested: {best.label}. {best.consequence}"}
    return Response(issues_zip(AuditReport.from_dict(data["report"]), fixes=fixes),
                    mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="repair-{plan_id[:8]}-issues.zip"'})


# -- sharing (spec 1.2) ------------------------------------------------------------------

@bp.route("/audit/<job_id>/repair/<plan_id>/members", methods=["POST"])
def repair_add_member(job_id, plan_id):
    data, plan, role = _plan_for(job_id, plan_id, need="share")
    body = request.get_json(silent=True) or {}
    who, new_role = str(body.get("account", "")).strip(), str(body.get("role", ""))
    if new_role not in ("approver", "reviewer"):
        return jsonify({"error": "role must be approver or reviewer"}), 400
    try:
        from models import User
        from sqlalchemy import func, or_
        user = User.query.filter(or_(func.lower(User.username) == who.lower(),
                                     func.lower(User.email) == who.lower())).first()
    except Exception:  # noqa: BLE001 - served without the app's user table
        user = None
    if user is None:
        return jsonify({"error": "No account with that username or email."}), 400
    if not access.account_may_repair(user):
        return jsonify({"error": "That account may not use guided repair (not in "
                                 "REPAIR_ALLOWED_USERS and not a power user)."}), 400
    if user.id == (data.get("owner") or {}).get("user_id"):
        return jsonify({"error": "The owner already has every right."}), 400
    with storage.lock(storage.plan_dir(_upload_dir(), job_id, plan_id)):
        plan = storage.load(_upload_dir(), job_id, plan_id)
        plan.members = [m for m in plan.members if m.get("user_id") != user.id]
        m = {"user_id": user.id, "name": user.username, "role": new_role,
             "added_by": _me(), "added_at": now()}
        plan.members.append(m)
        plan.log.append({"action": "share", "member": user.username, "role": new_role, "by": _me(), "at": now()})
        storage.save(_upload_dir(), plan)
    return jsonify(m)


@bp.route("/audit/<job_id>/repair/<plan_id>/members/<int:user_id>", methods=["DELETE"])
def repair_remove_member(job_id, plan_id, user_id):
    _plan_for(job_id, plan_id, need="share")
    with storage.lock(storage.plan_dir(_upload_dir(), job_id, plan_id)):
        plan = storage.load(_upload_dir(), job_id, plan_id)
        before = len(plan.members)
        plan.members = [m for m in plan.members if m.get("user_id") != user_id]
        if len(plan.members) == before:
            abort(404)
        plan.log.append({"action": "unshare", "member": user_id, "by": _me(), "at": now()})
        storage.save(_upload_dir(), plan)
    return jsonify({"ok": True})


def startup_line():
    return access.describe()



# -- pull requests (spec 6; owner only, own token, explicit confirmation) -------------------

@bp.route("/audit/<job_id>/repair/<plan_id>/github-token", methods=["POST", "DELETE"])
def repair_github_token(job_id, plan_id):
    from .release_repair import github
    _plan_for(job_id, plan_id, need="pull_request")
    uid = _me()["user_id"]
    if request.method == "DELETE":
        return jsonify({"deleted": github.delete_token(_upload_dir(), uid)})
    try:
        github.store_token(_upload_dir(), uid, (request.get_json(silent=True) or {}).get("token"))
    except github.GitHubError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"stored": True})


@bp.route("/audit/<job_id>/repair/<plan_id>/pull-request", methods=["POST"])
def repair_pull_request(job_id, plan_id):
    import shutil
    import tempfile
    from .release_repair import github
    from .release_repair.apply import materialize
    data, plan, role = _plan_for(job_id, plan_id, need="pull_request")
    body = request.get_json(silent=True) or {}
    state = storage.read_apply(_upload_dir(), job_id, plan_id)
    work = os.path.join(storage.plan_dir(_upload_dir(), job_id, plan_id), "work")
    if state.get("status") != "done" or not os.path.isdir(work):
        return jsonify({"error": "Apply the plan first (the patched copy is kept for "
                                 f"{storage.retention_days()} days)."}), 409
    release = storage.release_source(_upload_dir(), job_id, data)
    if release is None:
        return jsonify({"error": "The release is no longer stored; upload it again."}), 409
    token = github.load_token(_upload_dir(), _me()["user_id"])
    if token is None:
        return jsonify({"error": "Store your own GitHub token first; the service has none."}), 400
    tmp = tempfile.mkdtemp(prefix="owltester-pr-")
    try:
        materialize(release, os.path.join(tmp, "original"))
        changes = github.changed_files(os.path.join(tmp, "original"), work)
        if not body.get("confirm"):
            # First call: show exactly what would be pushed; nothing leaves the server.
            return jsonify({"confirm_needed": True, "files": [rel for rel, _ in changes],
                            "repo": body.get("repo"), "base": body.get("base")})
        fixlog = ""
        path = os.path.join(storage.plan_dir(_upload_dir(), job_id, plan_id), "out", "FIXLOG.md")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                fixlog = fh.read()
        result = github.open_pull_request(
            token, str(body.get("repo", "")), str(body.get("base", "main")), str(body.get("prefix", "")),
            changes, title=f"Repair {plan.artifact}: guided release repair plan {plan_id[:8]}",
            body=fixlog[:60000] + "\n\nOpened by OwlTester guided release repair.",
            branch=f"owltester-repair-{plan_id[:8]}")
    except github.GitHubError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with storage.lock(storage.plan_dir(_upload_dir(), job_id, plan_id)):
        plan = storage.load(_upload_dir(), job_id, plan_id)
        plan.log.append({"action": "pull_request", "url": result["url"], "by": _me(), "at": now()})
        storage.save(_upload_dir(), plan)
    return jsonify(result)
