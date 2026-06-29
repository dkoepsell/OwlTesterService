"""HTTP service — a thin Flask blueprint over the gate library.

Endpoints (section 2 of the spec):
    POST /check       multipart file or JSON {path|content} -> report
    POST /repair      -> {status, report, quarantine, repaired?}
    GET  /report/{id} -> the stored report

Mountable on the existing app:  app.register_blueprint(owltester.service.bp)
"""

import os
import tempfile

from flask import Blueprint, jsonify, request

from .pipeline import check, baseline_for
from .repair import repair as repair_artifact
from .kernel import default_kernel_path
from . import report_store

bp = Blueprint("owltester", __name__, url_prefix="/owltester")

_CONFIG = {"kernel_path": None}


def configure(kernel_path=None):
    _CONFIG["kernel_path"] = kernel_path or default_kernel_path()


def _kernel():
    return _CONFIG["kernel_path"] or default_kernel_path()


def _materialize(req):
    """Get a temp file path for the artifact from a multipart upload or a JSON
    body ({content, filename} or {path}). Returns (path, cleanup_bool)."""
    if req.files:
        f = next(iter(req.files.values()))
        suffix = os.path.splitext(f.filename or "artifact.owl")[1] or ".owl"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        f.save(path)
        return path, True
    data = req.get_json(silent=True) or {}
    if data.get("path"):
        return data["path"], False
    if data.get("content"):
        suffix = os.path.splitext(data.get("filename", "artifact.owl"))[1] or ".owl"
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data["content"])
        return path, True
    raise ValueError("no artifact: provide a file upload, or JSON {content} / {path}")


@bp.route("/check", methods=["POST"])
def http_check():
    cleanup = False
    path = None
    try:
        path, cleanup = _materialize(request)
        all_stages = request.args.get("all", "false").lower() in ("1", "true", "yes")
        report = check(path, kernel_path=_kernel(), all_stages=all_stages)
        d = report.to_dict()
        d["report_id"] = report_store.put(d)
        status = 200 if d["verdict"] == "pass" else 422
        return jsonify(d), status
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        if cleanup and path and os.path.exists(path):
            os.unlink(path)


@bp.route("/repair", methods=["POST"])
def http_repair():
    cleanup = False
    path = None
    try:
        path, cleanup = _materialize(request)
        max_removed = float(request.args.get("max_removed", 0.02))
        serialized, result = repair_artifact(
            path, kernel_path=_kernel(), max_removed=max_removed)
        out = {
            "status": result["status"],
            "quarantine": result["quarantine"],
            "report": result["report"],
            "error": result.get("error"),
        }
        out["report_id"] = report_store.put(result["report"])
        if serialized is not None:
            out["repaired"] = serialized.decode() if isinstance(serialized, bytes) else serialized
        code = 200 if result["status"] in ("unchanged", "repaired") else 422
        return jsonify(out), code
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        if cleanup and path and os.path.exists(path):
            os.unlink(path)


@bp.route("/report/<rid>", methods=["GET"])
def http_report(rid):
    d = report_store.get(rid)
    if d is None:
        return jsonify({"error": "report not found"}), 404
    return jsonify(d), 200
