"""The Kindwork module operations, shared by the HTTP routes and the MCP tools.

build, import, lint, ingest and propose go straight to the sidecar. check is the
three-step flow from module spec section 6: sidecar `prepare`, OwlTester's
reasoner, sidecar `findings`. propose only ever returns proposals; nothing it
says counts until a person confirms the term in the page.
"""

from __future__ import annotations

import base64
import binascii

from kindwork import sidecar
from kindwork.sidecar import PROPOSE_TIMEOUT
from kindwork.module_reasoner import REASONER, reason_text

MAX_SOURCE_BYTES = 8 * 1024 * 1024


def _args(source, name, fmt=None):
    if not isinstance(source, str) or not source.strip():
        raise sidecar.SidecarInputError(
            "Send the model, keyword source, or ontology as text in `source`.")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise sidecar.SidecarInputError(
            "That input is over 8 MB. Split it, or check it in OwlTester directly.")
    out = {"source": source, "name": name if isinstance(name, str) and name else "model"}
    if fmt in ("kw", "json", "turtle", "rdfxml"):
        out["format"] = fmt
    return out


def build(source, name=None, fmt=None):
    return sidecar.call("build", **_args(source, name, fmt))


def import_model(source, name=None):
    return sidecar.call("import", **_args(source, name))


def lint(source, name=None):
    reply = sidecar.call("lint", **_args(source, name))
    return {"errors": reply.get("errors", []), "warnings": reply.get("warnings", [])}


def check(source, name=None):
    args = _args(source, name)
    prepared = sidecar.call("prepare", **args)
    onto = prepared["ontology"]
    result = reason_text(onto["text"], onto.get("ext", "ttl"))
    doc = sidecar.call("findings", reasoner=result, **args)
    doc["reasoner"] = dict(REASONER) if result["status"] != "unavailable" else None
    return doc


def ingest(name, b64):
    if not isinstance(name, str) or not name.strip():
        raise sidecar.SidecarInputError("Send the file name in `name`.")
    if not isinstance(b64, str) or not b64:
        raise sidecar.SidecarInputError("Send the file contents, base64 encoded, in `base64`.")
    try:
        size = len(base64.b64decode(b64, validate=True))
    except (binascii.Error, ValueError) as e:
        raise sidecar.SidecarInputError("The file contents are not valid base64.") from e
    if size > MAX_SOURCE_BYTES:
        raise sidecar.SidecarInputError("That file is over 8 MB. Split it and try again.")
    return sidecar.call("ingest", name=name[:200], base64=b64)


def propose(kind, terms=None, context=None, task=None):
    """Proposals only. The sidecar builds the prompt from the page's own builders."""
    if kind == "task":
        payload = {"kind": "task", "task": task if isinstance(task, str) else ""}
    elif kind == "terms":
        clean = [{"name": str(t.get("name"))[:80], "desc": str(t.get("desc") or "")[:300],
                  "hints": str(t.get("hints") or "")[:200]}
                 for t in (terms if isinstance(terms, list) else [])
                 if isinstance(t, dict) and t.get("name")]
        payload = {"kind": "terms", "terms": clean,
                   "context": context if isinstance(context, str) else ""}
    else:
        raise sidecar.SidecarInputError('kind must be "task" or "terms".')
    reply = sidecar.call("propose", timeout=PROPOSE_TIMEOUT, **payload)
    return {"result": reply.get("result"), "model": reply.get("model")}


def health():
    reply = sidecar.call("health")
    return {"ok": bool(reply.get("ok")), "core": reply.get("core"),
            "reasoner": dict(REASONER), "coreHash": sidecar.core_hash()}
