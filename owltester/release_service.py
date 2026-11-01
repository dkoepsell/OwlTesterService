"""HTTP surface of the release builder (SPEC-release.md, sections 8, 9 and 13).

Pages (``release_pages_bp``):
    GET  /release/new                       upload the ontology (and optional files)
    POST /release/new                       create a build and go to its first step
    GET  /release/<id>/step/<step>          one page per step; POST saves it and moves on
    GET  /release/<id>                      status, outputs, audit, repair and publish
JSON / downloads:
    GET  /release/<id>/status               {status, step, report}
    GET  /release/<id>/out/<name>           zip, repo, report, htaccess, w3id-pr, shapes-draft
    POST /release/<id>/repair               hand the built release to guided repair
    POST /release/<id>/repaired             take a repair plan's output, audit and record it again
    POST /release/<id>/publish              GitHub: a dry run, then {confirm: true} pushes
    POST|DELETE /release/github-token       the owner's own token, stored encrypted

Access: signed in, and named in BUILD_ALLOWED_USERS or a power user (owltester/power.py); a build
belongs to the account that started it and only that account can see it (404
otherwise). Publishing is owner only and confirmed each time.
"""

import datetime
import json
import logging
import os
import re
import shutil
import threading
import uuid

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, \
    send_from_directory, url_for
from werkzeug.utils import secure_filename

from .release import answers as A
from .release_repair import access as repair_access

logger = logging.getLogger(__name__)
release_pages_bp = Blueprint("release_pages", __name__)

BUILD_ID = re.compile(r"^[0-9a-f]{32}$")
STEPS = ("identity", "imports", "build", "quality", "review")
ONTOLOGY_EXT = {"owl", "ttl", "rdf", "xml", "nt", "n3", "jsonld", "ofn", "owx", "omn"}
DATA_EXT = ONTOLOGY_EXT | {"trig", "nq"}
STALE_SECONDS = 30 * 60
OUTPUTS = {"zip": None, "repo": None, "report": "build-report.json", "htaccess": "w3id/.htaccess",
           "w3id-pr": "w3id/W3ID-PR.md"}


def allowed_users():
    raw = os.environ.get("BUILD_ALLOWED_USERS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def may_build():
    """Signed in, and named in BUILD_ALLOWED_USERS or a power user. Fails closed."""
    uid, username, email = repair_access.current()
    if uid is None:
        return False
    if repair_access.matches(allowed_users(), username, email):
        return True
    from .power import is_power_user
    return is_power_user()


def describe():
    allow = sorted(allowed_users())
    named = 'only ' + ', '.join(allow) if allow else 'no one named (BUILD_ALLOWED_USERS is empty)'
    return f"release builder: {named} plus power users"


def _root():
    return os.path.join(os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads")), "releases")


def _dir(build_id):
    return os.path.join(_root(), build_id)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _read(build_id):
    try:
        with open(os.path.join(_dir(build_id), "build.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(data):
    data["updated_at"] = _now()
    path = os.path.join(_dir(data["build_id"]), "build.json")
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(path + ".tmp", path)


def _build_or_404(build_id, start=False):
    if not may_build():
        abort(403 if start else 404)
    data = _read(build_id) if BUILD_ID.match(build_id or "") else None
    uid = repair_access.current()[0]
    if data is None or (data.get("owner") or {}).get("user_id") != uid:
        abort(404)
    if data.get("status") == "running":
        try:
            age = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                   - datetime.datetime.fromisoformat(data["updated_at"])).total_seconds()
        except (KeyError, ValueError):
            age = 0
        if age > STALE_SECONDS:
            data.update(status="error", error="The build stopped reporting (the server restarted). Build again.")
    return data


def _save_uploads(files, dest, allowed):
    names = []
    for f in files:
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        if not name or name.rsplit(".", 1)[-1].lower() not in allowed:
            raise ValueError(f"Unsupported file: {name or 'unnamed'}")
        os.makedirs(dest, exist_ok=True)
        f.save(os.path.join(dest, name))
        names.append(name)
    return names


# -- pages -------------------------------------------------------------------------------

@release_pages_bp.route("/release/new", methods=["GET"])
def release_new():
    if not may_build():
        abort(403)
    return render_template("release_new.html", error=None)


@release_pages_bp.route("/release/new", methods=["POST"])
def release_create():
    from .release import imports, metadata
    if not may_build():
        abort(403)
    build_id = uuid.uuid4().hex
    d = _dir(build_id)
    os.makedirs(os.path.join(d, "input"))
    try:
        onto = _save_uploads([request.files.get("ontology")], os.path.join(d, "input"), ONTOLOGY_EXT)
        if len(onto) != 1:
            raise ValueError("Upload one ontology file.")
        inputs = {"ontology": onto[0]}
        for key, sub, ext in (("imports", "imports", ONTOLOGY_EXT), ("shapes", "shapes", DATA_EXT),
                              ("vocabs", "vocab", DATA_EXT), ("examples", "examples", DATA_EXT)):
            inputs[key] = _save_uploads(request.files.getlist(key), os.path.join(d, sub), ext)
        prev = _save_uploads([request.files.get("previous")], os.path.join(d, "previous"), {"zip"})
        inputs["previous"] = prev[0] if prev else None
        g = metadata.read(os.path.join(d, "input", onto[0]))
    except (ValueError, OSError) as e:
        shutil.rmtree(d, ignore_errors=True)
        return render_template("release_new.html", error=str(e)), 400
    head = metadata.header(g)
    stem = re.sub(r"\.(owl|ttl|rdf|xml|nt|jsonld|ofn|owx|omn)$", "", onto[0].lower())
    draft = {"name": re.sub(r"[^a-z0-9-]+", "-", stem).strip("-")[:64] or "my-ontology",
             "title": head.get("title") or "", "description": head.get("description") or "",
             "ontology_iri": head.get("ontology_iri") or "", "version": head.get("version") or "0.1.0",
             "license": "CC-BY-4.0", "creators": head.get("creators") or [],
             "contributors": head.get("contributors") or [],
             "bfo": "module" if imports.bfo_terms(g) else "none", "formats": [], "fail_on": "major",
             "shapes_scaffold": "draft", "release_date": datetime.date.today().isoformat()}
    uid, username, email = repair_access.current()
    data = {"build_id": build_id, "owner": {"user_id": uid, "name": username or email},
            "created_at": _now(), "status": "draft", "inputs": inputs, "header": head,
            "detected": imports.detect(g), "answers": draft}
    _write(data)
    return redirect(url_for("release_pages.release_step", build_id=build_id, step=STEPS[0]))


def _people(text):
    out = []
    for line in (text or "").splitlines():
        if line.strip():
            name, _, orcid = line.partition(",")
            out.append({"name": name.strip(), "orcid": orcid.strip() or None})
    return out


def _apply_form(answers, step, form):
    if step == "identity":
        for k in ("name", "title", "description", "ontology_iri", "base", "version", "license",
                  "prior_version", "repository", "w3id_project", "release_date"):
            if k in form:
                answers[k] = form.get(k, "").strip()
        answers["creators"] = _people(form.get("creators"))
        answers["contributors"] = _people(form.get("contributors"))
    elif step == "imports":
        answers["bfo"] = form.get("bfo", "none")
    elif step == "build":
        answers["formats"] = form.getlist("formats")
        answers["profile"] = form.get("profile") or None
        answers["fail_on"] = form.get("fail_on", "major")
    elif step == "quality":
        answers["shapes_scaffold"] = form.get("shapes_scaffold", "draft")
        expected = []
        for line in (form.get("expected") or "").splitlines():
            code, _, reason = line.partition(":")
            if code.strip():
                expected.append({"finding": code.strip(), "reason": reason.strip()})
        answers["expected"] = expected
    return answers


@release_pages_bp.route("/release/<build_id>/step/<step>", methods=["GET", "POST"])
def release_step(build_id, step):
    data = _build_or_404(build_id)
    if step not in STEPS:
        abort(404)
    if request.method == "POST":
        if data.get("status") == "running":
            abort(409, description="The build is running.")
        if step == "imports" and request.files.getlist("imports"):
            try:
                data["inputs"]["imports"] += _save_uploads(request.files.getlist("imports"),
                                                           os.path.join(_dir(build_id), "imports"), ONTOLOGY_EXT)
            except ValueError as e:
                return render_template("release_step.html", b=data, step=step, steps=STEPS,
                                       problems=[str(e)], licenses=A.LICENSES), 400
        _apply_form(data["answers"], step, request.form)
        data["step"] = step
        _write(data)
        if step == "review":
            try:
                A.validate(data["answers"])
            except A.AnswersError as e:
                return render_template("release_step.html", b=data, step=step, steps=STEPS,
                                       problems=e.problems, licenses=A.LICENSES), 400
            _start(data)
            return redirect(url_for("release_pages.release_page", build_id=build_id))
        nxt = STEPS[min(STEPS.index(step) + 1, len(STEPS) - 1)]
        return redirect(url_for("release_pages.release_step", build_id=build_id, step=nxt))
    problems = []
    if step == "review":
        try:
            A.validate(data["answers"])
        except A.AnswersError as e:
            problems = e.problems
    return render_template("release_step.html", b=data, step=step, steps=STEPS, problems=problems,
                           licenses=A.LICENSES)


@release_pages_bp.route("/release/<build_id>", methods=["GET"])
def release_page(build_id):
    data = _build_or_404(build_id)
    return render_template("release_build.html", b=data, steps=STEPS,
                           may_repair=repair_access.may_repair(),
                           report=_report(build_id))


def _report(build_id):
    try:
        with open(os.path.join(_dir(build_id), "out", "build-report.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@release_pages_bp.route("/release/<build_id>/status", methods=["GET"])
def release_status(build_id):
    data = _build_or_404(build_id)
    rep = _report(build_id) or {}
    return jsonify({"status": data.get("status"), "stage": data.get("stage"), "error": data.get("error"),
                    "audit": rep.get("audit"), "warnings": rep.get("warnings", [])})


# -- the build job -----------------------------------------------------------------------

def _start(data):
    from .release.builder import build
    app = current_app._get_current_object()
    d = _dir(data["build_id"])
    data.update(status="running", stage="starting", error=None)
    _write(data)
    inp = data["inputs"]
    files = lambda sub, names: [os.path.join(d, sub, n) for n in names or []]

    def progress(name, note=""):
        data["stage"] = f"{name}: {note}" if note else name
        _write(data)

    def go():
        with app.app_context():
            try:
                rep = build(os.path.join(d, "input", inp["ontology"]), data["answers"], os.path.join(d, "out"),
                            supplied_imports=files("imports", inp.get("imports")),
                            shapes=files("shapes", inp.get("shapes")), vocabs=files("vocab", inp.get("vocabs")),
                            examples=files("examples", inp.get("examples")),
                            previous=os.path.join(d, "previous", inp["previous"]) if inp.get("previous") else None,
                            progress=progress, budget=int(os.environ.get("BUILD_BUDGET", "300")))
                data.update(status=rep["status"], stage="")
            except Exception as e:  # noqa: BLE001 - shown on the build page
                logger.warning("release build %s failed: %s", data["build_id"], e)
                data.update(status="error", stage="", error=f"{type(e).__name__}: {str(e)[:600]}")
            _write(data)

    threading.Thread(target=go, name=f"release-build-{data['build_id'][:8]}", daemon=True).start()


@release_pages_bp.route("/release/<build_id>/out/<name>", methods=["GET"])
def release_out(build_id, name):
    _build_or_404(build_id)
    rep = _report(build_id)
    if name not in OUTPUTS or rep is None:
        abort(404)
    out = os.path.join(_dir(build_id), "out")
    rel = {"zip": rep["outputs"]["zip"], "repo": rep["outputs"]["repo_zip"]}.get(name) or OUTPUTS[name]
    if not os.path.isfile(os.path.join(out, rel)):
        abort(404)
    return send_from_directory(out, rel, as_attachment=True, download_name=os.path.basename(rel) or name)


# -- guided repair -----------------------------------------------------------------------

@release_pages_bp.route("/release/<build_id>/repair", methods=["POST"])
def release_repair(build_id):
    """Hand the assembled release to guided repair: an audit job owned by the same account,
    with the release kept, so /audit/<job>/repair works on it."""
    from .audit import jobs
    data = _build_or_404(build_id)
    rep = _report(build_id)
    if rep is None or not repair_access.may_repair():
        abort(403)
    up = os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))
    with open(os.path.join(_dir(build_id), "out", rep["outputs"]["release_dir"], "audit", "report.json"),
              encoding="utf-8") as fh:
        report = json.load(fh)
    job_id, jd = jobs.create(up, {"user_id": data["owner"]["user_id"]}, report["artifact"], report["profile"])
    shutil.copyfile(os.path.join(_dir(build_id), "out", rep["outputs"]["zip"]),
                    os.path.join(jd, "release.zip.tmp"))
    os.makedirs(os.path.join(jd, "release"), exist_ok=True)
    os.replace(os.path.join(jd, "release.zip.tmp"), os.path.join(jd, "release", rep["outputs"]["zip"]))
    jobs.update(up, job_id, status="done", report=report, release_files=[rep["outputs"]["zip"]],
                release_build=build_id)
    data["repair_job"] = job_id
    _write(data)
    return redirect(url_for("audit_pages.repair_home", job_id=job_id))


@release_pages_bp.route("/release/<build_id>/repaired", methods=["POST"])
def release_repaired(build_id):
    from .release.builder import repackage
    from .release_repair import storage
    data = _build_or_404(build_id)
    job_id, plan_id = data.get("repair_job"), (request.form.get("plan_id") or "").strip()
    if not job_id or not storage.PLAN_ID.match(plan_id):
        abort(400)
    up = os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))
    state = storage.read_apply(up, job_id, plan_id)
    zname = ((state.get("result") or {}).get("outputs") or {}).get("zip")
    path = os.path.join(storage.plan_dir(up, job_id, plan_id), "out", zname or "")
    if state.get("status") != "done" or not zname or not os.path.isfile(path):
        abort(409, description="Apply the repair plan first.")
    repackage(os.path.join(_dir(build_id), "out"), path, data["answers"])
    rep = _report(build_id)
    data.update(status=rep["status"], repaired_from=plan_id)
    _write(data)
    return redirect(url_for("release_pages.release_page", build_id=build_id))


# -- publishing --------------------------------------------------------------------------

@release_pages_bp.route("/release/github-token", methods=["POST", "DELETE"])
def release_github_token():
    from .release_repair import github
    if not may_build():
        abort(404)
    uid = repair_access.current()[0]
    up = os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))
    if request.method == "DELETE":
        return jsonify({"deleted": github.delete_token(up, uid)})
    try:
        github.store_token(up, uid, (request.get_json(silent=True) or {}).get("token"))
    except github.GitHubError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"stored": True})


@release_pages_bp.route("/release/<build_id>/publish", methods=["POST"])
def release_publish(build_id):
    from .audit.files import extract_zip
    from .release import publish
    from .release_repair import github
    data = _build_or_404(build_id)
    if (data.get("owner") or {}).get("user_id") != repair_access.current()[0]:
        abort(403)
    rep = _report(build_id)
    if rep is None or rep.get("status") != "done":
        return jsonify({"error": "Only a built release whose audit passed its gate can be published."}), 409
    body = request.get_json(silent=True) or {}
    repo, create = str(body.get("repo", "")).strip(), bool(body.get("create"))
    out = os.path.join(_dir(build_id), "out")
    tmp = os.path.join(_dir(build_id), "publish")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        extract_zip(os.path.join(out, rep["outputs"]["repo_zip"]), tmp)
        files = publish.scaffold_files(tmp)
        try:
            plan = publish.plan(repo, data["answers"]["version"], files, rep["outputs"]["zip"], create)
        except github.GitHubError as e:
            return jsonify({"error": str(e)}), 400
        if not body.get("confirm"):
            return jsonify({"dry_run": True, **plan})
        up = os.path.realpath(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"))
        token = github.load_token(up, data["owner"]["user_id"])
        if not token:
            return jsonify({"error": "Store your GitHub token first."}), 400
        with open(os.path.join(out, rep["outputs"]["release_dir"], "VERIFICATION.md"), encoding="utf-8") as fh:
            notes = fh.read()
        try:
            result = publish.publish(token, repo, data["answers"]["version"], files,
                                     os.path.join(out, rep["outputs"]["zip"]), notes, create=create)
        except github.GitHubError as e:
            return jsonify({"error": str(e)}), 502
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    data.setdefault("published", []).append({"at": _now(), **result})
    _write(data)
    return jsonify(result)
