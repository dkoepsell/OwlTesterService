"""HTTP and MCP surface of the Kindwork module (module spec sections 5 and 6).

/kindwork/v1/{health,build,import,lint,check}   JSON in, JSON out
/kindwork/mcp                                   stateless streamable-HTTP MCP (JSON replies)

Auth follows OwlTester's API: public and rate-limited. Setting KINDWORK_TOKEN
additionally requires `Authorization: Bearer <token>` on every route but health.
Every reply carries X-Kindwork-Core. Input is never persisted.
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import os
import zipfile

from flask import Blueprint, Response, jsonify, request

from kindwork import module
from kindwork.sidecar import SidecarError, SidecarInputError, core_hash

logger = logging.getLogger(__name__)

MAX_BODY = 8 * 1024 * 1024

module_bp = Blueprint("kindwork_module", __name__)


@module_bp.before_request
def _guard():
    if request.method == "OPTIONS":
        return None
    length = request.content_length
    if length is not None and length > MAX_BODY:
        return jsonify(error="The request is over 8 MB."), 413
    if length is None and request.method == "POST":
        if len(request.get_data(cache=True)) > MAX_BODY:
            return jsonify(error="The request is over 8 MB."), 413
    token = os.environ.get("KINDWORK_TOKEN")
    if token and request.endpoint != "kindwork_module.health":
        sent = request.headers.get("Authorization", "")
        if not (sent.startswith("Bearer ") and hmac.compare_digest(sent[7:], token)):
            return jsonify(error="Send Authorization: Bearer <token>."), 401
    return None


@module_bp.after_request
def _stamp(resp):
    resp.headers["X-Kindwork-Core"] = core_hash()
    return resp


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise SidecarInputError("Send a JSON object with `source` and `name`.")
    return data


def _input_error(e):
    return jsonify(error=str(e), errors=e.diagnostics), 422


def _internal(e):
    logger.error("kindwork module: %s", e)
    return jsonify(error="The Kindwork module is not available right now."), 503


@module_bp.get("/kindwork/v1/health")
def health():
    try:
        return jsonify(module.health())
    except SidecarError as e:
        return jsonify(ok=False, core=str(e), reasoner=None), 503


@module_bp.post("/kindwork/v1/build")
def build():
    try:
        b = _body()
        reply = module.build(b.get("source"), b.get("name"), b.get("format"))
    except SidecarInputError as e:
        return _input_error(e)
    except SidecarError as e:
        return _internal(e)
    if request.accept_mimetypes.best == "application/zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, text in reply["files"].items():
                z.writestr(f"{reply['slug']}/{name}", text)
        return Response(buf.getvalue(), mimetype="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{reply["slug"]}.zip"'})
    return jsonify(reply)


@module_bp.post("/kindwork/v1/import")
def import_model():
    try:
        b = _body()
        return jsonify(module.import_model(b.get("source"), b.get("name")))
    except SidecarInputError as e:
        return _input_error(e)
    except SidecarError as e:
        return _internal(e)


@module_bp.post("/kindwork/v1/lint")
def lint():
    try:
        b = _body()
        return jsonify(module.lint(b.get("source"), b.get("name")))
    except SidecarInputError as e:
        return jsonify(error=str(e), errors=e.diagnostics), 422
    except SidecarError as e:
        return _internal(e)


@module_bp.post("/kindwork/v1/check")
def check():
    try:
        b = _body()
        return jsonify(module.check(b.get("source"), b.get("name")))
    except SidecarInputError as e:
        return _input_error(e)
    except SidecarError as e:
        return _internal(e)


# --- MCP ---------------------------------------------------------------------

_SRC = {"type": "string", "description": "Keyword source, kindwork-model JSON, Turtle, or RDF/XML."}
_NAME = {"type": "string", "description": "File name; its extension disambiguates .kw."}
_SCHEMA = {"type": "object", "properties": {"source": _SRC, "name": _NAME},
           "required": ["source"], "additionalProperties": False}

TOOLS = [
    ("kindwork_build", module.build,
     "Compile a Kindwork model or keyword source into BFO 2020 OWL, SHACL shapes, a standalone "
     "tracker app, keyword source and a model file. Returns the files and any warnings."),
    ("kindwork_lint", module.lint,
     "Check Kindwork keyword source and return line-numbered errors and warnings in plain "
     "language. Does not build."),
    ("kindwork_import", module.import_model,
     "Read an ontology (Turtle or RDF/XML) or Kindwork model and return a Kindwork model, with "
     "each class placed by its BFO 2020 ancestors and straddles flagged."),
    ("kindwork_check", module.check,
     "Run the OwlTester reasoner on a Kindwork model, keyword source or ontology and return "
     "findings in plain language, three-valued: fail, undetermined, pass."),
]
_BY_NAME = {name: fn for name, fn, _ in TOOLS}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _text(obj, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}],
            "isError": is_error}


def _call_tool(params):
    name = params.get("name")
    args = params.get("arguments") or {}
    fn = _BY_NAME.get(name)
    if fn is None:
        return None
    try:
        return _text(fn(args.get("source"), args.get("name")))
    except SidecarInputError as e:
        errors = sorted(e.diagnostics, key=lambda d: (d.get("line") is None, d.get("line") or 0))
        return _text({"error": str(e), "errors": errors}, is_error=True)
    except SidecarError as e:
        logger.error("kindwork mcp %s: %s", name, e)
        return _text({"error": "The Kindwork module is not available right now."}, is_error=True)


def _dispatch(msg):
    """One JSON-RPC message -> reply dict, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid request"}}
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "owltester-kindwork", "version": "0.1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": _SCHEMA}
                            for n, _, d in TOOLS]}
    elif method == "tools/call":
        result = _call_tool(params)
        if result is None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


@module_bp.route("/kindwork/mcp", methods=["GET", "POST", "DELETE"])
def mcp():
    if request.method != "POST":
        return Response(status=405, headers={"Allow": "POST"})
    try:
        payload = json.loads(request.get_data(as_text=True))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32700, "message": "Parse error"}), 400
    if isinstance(payload, list):
        replies = [r for r in map(_dispatch, payload) if r is not None]
        return (jsonify(replies), 200) if replies else Response(status=202)
    reply = _dispatch(payload)
    return jsonify(reply) if reply is not None else Response(status=202)
