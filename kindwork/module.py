"""The four Kindwork module operations, shared by the HTTP routes and the MCP tools.

build, import and lint go straight to the sidecar. check is the three-step flow
from module spec section 2: sidecar `prepare`, OwlTester's reasoner, sidecar
`findings`.
"""

from __future__ import annotations

from kindwork import sidecar
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


def health():
    reply = sidecar.call("health")
    return {"ok": bool(reply.get("ok")), "core": reply.get("core"),
            "reasoner": dict(REASONER), "coreHash": sidecar.core_hash()}
