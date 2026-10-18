"""HTTP and MCP surface of the Kindwork module (module spec sections 7 and 8).

GET  /kindwork                       the vendored Kindwork page, host config injected
/kindwork/v1/{health,ingest,propose,check,build,import,lint}   JSON in, JSON out
POST /kindwork/v1/event              measurement beacon (section 9): an event name only
/kindwork/mcp                        stateless MCP over HTTP (JSON replies), six tools

KINDWORK_MODE picks the phase: `triage` (P1, the default) is anonymous and
rate-limited; `full` (P2) requires OwlTester's sign-in, or a bearer token equal
to KINDWORK_TOKEN when one is set. Every reply carries X-Kindwork-Core. Nothing a
person sends is stored after the reply, except the counts in kindwork.metrics.

/propose runs on the visitor's own AI key, the same one "generate implications"
uses (api_key_utils, held in the session only). API and MCP clients without a
session send it as `X-AI-Key` (and `X-AI-Provider`). Server keys are never used.
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import os
import zipfile

from flask import Blueprint, Response, current_app, jsonify, redirect, request, url_for
from flask_login import current_user

from kindwork import metrics, module
from kindwork.sidecar import (PAGE, SidecarError, SidecarInputError, SidecarUpstreamError,
                              core_hash)

logger = logging.getLogger(__name__)

MAX_BODY = 8 * 1024 * 1024
# Base64 inflates a file by a third; allow an 8 MB file through /ingest.
MAX_INGEST_BODY = 11 * 1024 * 1024 + 4096
RATE_MESSAGE = "Too many requests just now. Try again in a minute."
VIEWPORT_META = '<meta name="claude:viewport-fit-sides" content="cover">'

# Section 7 P1 limits, per IP unless global.
PROPOSE_LIMITS = (("20/hour", "ip"), ("300/day", "global"))
CHECK_LIMITS = (("60/hour", "ip"),)

module_bp = Blueprint("kindwork_module", __name__)


def mode():
    return "full" if os.environ.get("KINDWORK_MODE", "triage").lower() == "full" else "triage"


def _signed_in():
    try:
        return bool(current_user.is_authenticated)
    except Exception:  # noqa: BLE001
        return False


def _token_ok():
    token = os.environ.get("KINDWORK_TOKEN")
    sent = request.headers.get("Authorization", "")
    return bool(token) and sent.startswith("Bearer ") and hmac.compare_digest(sent[7:], token)


class RateLimited(Exception):
    pass


def _enforce(limit_specs, name):
    """Count one hit against each limit; raise RateLimited when any is spent."""
    if not current_app.config.get("RATELIMIT_ENABLED", True):
        return
    from limits import parse
    from abuse_limits import limiter
    from flask_limiter.util import get_remote_address
    for spec, scope in limit_specs:
        key = "all" if scope == "global" else get_remote_address()
        if not limiter.limiter.hit(parse(spec), f"kindwork-{name}", key):
            raise RateLimited()


# --- guards ---------------------------------------------------------------------

PUBLIC_ENDPOINTS = {"kindwork_module.health"}


@module_bp.before_request
def _guard():
    if request.method == "OPTIONS":
        return None
    cap = MAX_INGEST_BODY if request.endpoint == "kindwork_module.ingest" else MAX_BODY
    length = request.content_length
    if length is not None and length > cap:
        return jsonify(error="The request is over 8 MB."), 413
    if length is None and request.method == "POST" and len(request.get_data(cache=True)) > cap:
        return jsonify(error="The request is over 8 MB."), 413
    if mode() == "full" and request.endpoint not in PUBLIC_ENDPOINTS:
        if not (_signed_in() or _token_ok()):
            if request.endpoint == "kindwork_module.page":
                return redirect(url_for("login", next=request.path))
            return jsonify(error="Sign in to OwlTester first."), 401
    elif os.environ.get("KINDWORK_TOKEN") and request.endpoint not in PUBLIC_ENDPOINTS | {
            "kindwork_module.page", "kindwork_module.event"} and not _token_ok():
        # Triage mode with a token configured: the page's own calls carry the
        # signed-in session instead, so only API clients need the header.
        if not _signed_in():
            return jsonify(error="Send Authorization: Bearer <token>."), 401
    return None


@module_bp.after_request
def _stamp(resp):
    resp.headers["X-Kindwork-Core"] = core_hash()
    return resp


@module_bp.errorhandler(RateLimited)
def _rate_limited(_e):
    return jsonify(code="rate_limited", error=RATE_MESSAGE), 429


@module_bp.errorhandler(429)
def _rate_limited_flask(_e):
    return jsonify(code="rate_limited", error=RATE_MESSAGE), 429


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise SidecarInputError("Send a JSON object.")
    return data


def _input_error(e):
    return jsonify(error=str(e), errors=e.diagnostics), 422


def _internal(e):
    logger.error("kindwork module: %s", e)
    return jsonify(code="unavailable", error="The Kindwork module is not available right now."), 503


# --- the page -------------------------------------------------------------------

def host_config():
    cfg = {"api": "/kindwork/v1", "mode": mode()}
    cta = {k: os.environ.get(f"KINDWORK_CTA_{k.upper()}") for k in ("title", "text", "href", "label")}
    if all(cta.values()):
        cfg["cta"] = cta
    return cfg


# Everything below runs inside the one injected script, so the vendored page
# stays untouched. The beacon reports an event name for section 9 and nothing
# else. The key bar lets a visitor add their own OpenAI or Anthropic key, the
# same session-only key "generate implications" uses, so Propose can run.
_BEACON = """(function(){var m={savecsv:'save-csv',saveowl:'save-ttl',savekit:'save-other',saveseed:'save-other',savetester:'save-other',savetracker:'save-other'};
document.addEventListener('click',function(e){var t=e.target&&e.target.closest&&e.target.closest('[data-act],.cta a');if(!t)return;
var ev=t.matches('.cta a')?'triage':m[t.getAttribute('data-act')];if(!ev||!navigator.sendBeacon)return;
try{navigator.sendBeacon(window.KINDWORK_HOST.api+'/event',new Blob([JSON.stringify({event:ev})],{type:'application/json'}));}catch(x){}},true);})();"""

_KEY_BAR = """(function(){var URL_='/api/settings/openai-key';
function el(tag,attrs,text){var e=document.createElement(tag);for(var k in attrs)e.setAttribute(k,attrs[k]);if(text)e.textContent=text;return e;}
function bar(){var b=document.getElementById('kw-keybar');if(b)return b;
b=el('div',{id:'kw-keybar',role:'region','aria-label':'Your AI key'});
b.style.cssText='font:14px/1.4 system-ui,sans-serif;padding:8px 16px;border-bottom:1px solid GrayText;background:Canvas;color:CanvasText;display:flex;flex-wrap:wrap;gap:8px;align-items:center';
document.body.insertBefore(b,document.body.firstChild);return b;}
function btn(label){var x=el('button',{type:'button'},label);x.style.cssText='font:inherit;padding:3px 10px;cursor:pointer';return x;}
function show(st,msg){var b=bar();b.textContent='';
var p=st.provider==='anthropic'?'Anthropic (Claude)':'OpenAI';
if(st.source==='session'){b.appendChild(el('span',{},'Propose answers uses your own '+p+' key. It stays in your session and is never saved.'));
var c=btn('Change key');c.onclick=function(){form(st);};b.appendChild(c);
var r=btn('Remove key');r.onclick=function(){fetch(URL_,{method:'DELETE',credentials:'same-origin'}).then(function(x){return x.json();}).then(function(j){show({source:'none'},'Key removed.');});};b.appendChild(r);}
else{b.appendChild(el('span',{},'To have AI propose answers, add your own OpenAI or Anthropic (Claude) key. It stays in your session and is never saved. Without one, you can still answer every question by hand.'));
var a=btn('Add your key');a.onclick=function(){form(st);};b.appendChild(a);}
if(msg)b.appendChild(el('span',{role:'status'},msg));}
function form(st){var b=bar();b.textContent='';
var sel=el('select',{'aria-label':'AI provider'});[['anthropic','Anthropic (Claude)'],['openai','OpenAI']].forEach(function(o){var op=el('option',{value:o[0]},o[1]);if((st.provider||'anthropic')===o[0])op.selected=true;sel.appendChild(op);});
var inp=el('input',{type:'password',autocomplete:'off','aria-label':'API key',placeholder:'sk-ant-...'});inp.style.cssText='font:inherit;min-width:16em;padding:3px 6px';
sel.onchange=function(){inp.placeholder=sel.value==='anthropic'?'sk-ant-...':'sk-...';};
var save=btn('Save'),cancel=btn('Cancel'),out=el('span',{role:'status'});
save.onclick=function(){out.textContent='Saving...';fetch(URL_,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:inp.value.trim(),provider:sel.value})})
.then(function(x){return x.json();}).then(function(j){if(j.success)show({source:'session',provider:j.provider},'Key saved.');else out.textContent=j.message||'That key was not accepted.';})
.catch(function(){out.textContent='The key could not be saved. Try again.';});};
cancel.onclick=function(){load();};
[el('span',{},'Your key:'),sel,inp,save,cancel,out].forEach(function(x){b.appendChild(x);});inp.focus();}
function load(){fetch(URL_,{credentials:'same-origin'}).then(function(x){return x.json();}).then(function(j){show({source:j.source,provider:j.provider});}).catch(function(){});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load);else load();})();"""


def render_page():
    html = PAGE.read_text(encoding="utf-8")
    if html.count(VIEWPORT_META) != 1:
        raise SidecarError("The vendored Kindwork page has no viewport-fit meta line.")
    cfg = json.dumps(host_config(), ensure_ascii=False).replace("</", "<\\/")
    script = f"<script>window.KINDWORK_HOST = {cfg};\n{_BEACON}\n{_KEY_BAR}</script>"
    return html.replace(VIEWPORT_META, VIEWPORT_META + "\n" + script, 1)


@module_bp.get("/kindwork")
def page():
    try:
        return Response(render_page(), mimetype="text/html")
    except (OSError, SidecarError) as e:
        logger.error("kindwork page: %s", e)
        return Response("Kindwork is not available right now.", status=503, mimetype="text/plain")


# --- JSON routes ------------------------------------------------------------------

@module_bp.get("/kindwork/v1/health")
def health():
    try:
        h = module.health()
        return jsonify(ok=h["ok"], core=h["core"], reasoner=h["reasoner"], coreHash=h["coreHash"])
    except SidecarError as e:
        return jsonify(ok=False, core=str(e), reasoner=None), 503


@module_bp.post("/kindwork/v1/ingest")
def ingest():
    try:
        b = _body()
        reply = module.ingest(b.get("name"), b.get("base64"))
    except SidecarInputError as e:
        return jsonify(error=str(e)), 422
    except SidecarError as e:
        return _internal(e)
    metrics.record_ingest(mode(), b.get("name") or "", len(reply.get("terms") or []))
    return jsonify(terms=reply.get("terms", []), truncated=bool(reply.get("truncated")),
                   context=reply.get("context", ""))


def visitor_ai():
    """(provider, key) from the visitor's own key, or None. Never a server key."""
    from api_key_utils import ai_key_source, resolve_ai
    if ai_key_source() == "session":
        provider, key = resolve_ai()
        if provider and key:
            return provider, key
    key = request.headers.get("X-AI-Key", "").strip()
    if key:
        asked = request.headers.get("X-AI-Provider", "").strip().lower()
        if key.startswith("sk-ant-"):
            return "anthropic", key
        return (asked if asked in ("openai", "anthropic") else "openai"), key
    return None


def _propose(b):
    _enforce(PROPOSE_LIMITS, "propose")
    return module.propose(b.get("kind"), b.get("terms"), b.get("context"), b.get("task"),
                          ai=visitor_ai())


@module_bp.post("/kindwork/v1/propose")
def propose():
    try:
        b = _body()
        reply = _propose(b)
    except SidecarInputError as e:
        return jsonify(error=str(e), errors=e.diagnostics), 422
    except SidecarUpstreamError as e:
        status = e.status if e.status in (429, 502, 503) else 502
        return jsonify(code=e.code, error=str(e)), status
    except SidecarError as e:
        return _internal(e)
    metrics.record_propose(mode(), b, reply)
    return jsonify(reply)


def _check(b):
    _enforce(CHECK_LIMITS, "check")
    return module.check(b.get("source"), b.get("name"))


@module_bp.post("/kindwork/v1/check")
def check():
    try:
        b = _body()
        doc = _check(b)
    except SidecarInputError as e:
        return _input_error(e)
    except SidecarError as e:
        return _internal(e)
    try:
        manifest = json.loads(b.get("source") or "")
    except (TypeError, ValueError):
        manifest = None
    if isinstance(manifest, dict) and manifest.get("format") == "kindwork-model":
        metrics.record_check(mode(), manifest, doc)
    return jsonify(doc)


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


@module_bp.post("/kindwork/v1/event")
def event():
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict) and isinstance(data.get("event"), str):
        metrics.record_event(mode(), data["event"][:32])
    return Response(status=204)


# --- MCP ----------------------------------------------------------------------------

_STR = {"type": "string"}
_SOURCE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["source"],
    "properties": {"source": {**_STR, "description": "Keyword source, kindwork-model JSON, Turtle, or RDF/XML."},
                   "name": {**_STR, "description": "File name; its extension disambiguates .kw."}}}
_TERM = {"type": "object", "required": ["name"], "additionalProperties": False,
         "properties": {"name": _STR, "desc": _STR, "hints": _STR}}


def _mcp_propose(args):
    return _propose({"kind": "terms", "terms": args.get("terms"), "context": args.get("context")})


def _mcp_source(fn):
    return lambda args: fn(args.get("source"), args.get("name"))


TOOLS = [
    ("kindwork_propose",
     {"type": "object", "additionalProperties": False, "required": ["terms"],
      "properties": {"terms": {"type": "array", "items": _TERM, "maxItems": 60},
                     "context": _STR}},
     _mcp_propose,
     "Propose answers to Kindwork's classification questions for a list of terms. Returns "
     "proposals only; a person must confirm each term before it counts."),
    ("kindwork_ingest",
     {"type": "object", "additionalProperties": False, "required": ["name", "base64"],
      "properties": {"name": _STR, "base64": _STR}},
     lambda args: module.ingest(args.get("name"), args.get("base64")),
     "Read a term list, spreadsheet, data dictionary, JSON Schema or SQL file and return "
     "candidate terms with meanings and hints. Does not classify."),
    ("kindwork_lint", _SOURCE_SCHEMA, _mcp_source(module.lint),
     "Check Kindwork keyword source and return line-numbered errors and warnings in plain "
     "language. Does not build."),
    ("kindwork_check", _SOURCE_SCHEMA, lambda args: _check(args),
     "Run the OwlTester reasoner on a Kindwork model, keyword source or ontology and return "
     "findings in plain language, three-valued: fail, undetermined, pass."),
    ("kindwork_build", _SOURCE_SCHEMA, _mcp_source(module.build),
     "Compile a Kindwork model or keyword source into BFO 2020 OWL, SHACL shapes, a standalone "
     "tracker app, keyword source, a classified list and a model file."),
    ("kindwork_import", _SOURCE_SCHEMA, _mcp_source(module.import_model),
     "Read an ontology (Turtle or RDF/XML) or Kindwork model into a Kindwork model, placing each "
     "class by its BFO 2020 ancestors and flagging straddles."),
]
_BY_NAME = {name: fn for name, _, fn, _ in TOOLS}
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
        return _text(fn(args if isinstance(args, dict) else {}))
    except SidecarInputError as e:
        errors = sorted(e.diagnostics, key=lambda d: (d.get("line") is None, d.get("line") or 0))
        return _text({"error": str(e), "errors": errors}, is_error=True)
    except RateLimited:
        return _text({"code": "rate_limited", "error": RATE_MESSAGE}, is_error=True)
    except SidecarUpstreamError as e:
        return _text({"code": e.code, "error": str(e)}, is_error=True)
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
                  "serverInfo": {"name": "owltester-kindwork", "version": "0.2.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s}
                            for n, s, _, d in TOOLS]}
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
