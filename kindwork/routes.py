"""HTTP surface for the Kindwork adapter.

GET  /kindwork/workbench  lint, check and build tools, and the export check
POST /kindwork/check  files (one, several, or a zip) -> <slug>.findings.json
GET  /kindwork/vocab  the kwv: vocabulary in Turtle (spec A1)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request

from kindwork.bundle import BundleRefused, load_bundle
from kindwork.check import check_bundle

logger = logging.getLogger(__name__)

kindwork_bp = Blueprint("kindwork", __name__, url_prefix="/kindwork")

VOCAB_PATH = Path(__file__).resolve().parent / "vocab.ttl"


@kindwork_bp.get("/workbench")
def page():
    return render_template("kindwork.html")


@kindwork_bp.post("/check")
def check():
    uploads = [(f.filename, f.read()) for f in request.files.getlist("files") if f.filename]
    if not uploads:
        return jsonify(error="Choose the files Kindwork exported, or a zip of them."), 400
    try:
        bundle = load_bundle(uploads)
    except BundleRefused as e:
        return jsonify(error=str(e)), 400
    try:
        doc = check_bundle(bundle)
    except Exception:  # noqa: BLE001
        logger.exception("kindwork check failed")
        return jsonify(error="The checks stopped with an internal error."), 500
    return Response(
        json.dumps(doc, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{bundle.slug}.findings.json"'},
    )


@kindwork_bp.get("/vocab")
def vocab():
    return Response(VOCAB_PATH.read_text(encoding="utf-8"), mimetype="text/turtle")
