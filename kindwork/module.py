"""The Kindwork module operations, shared by the HTTP routes and the MCP tools.

build, import, lint, ingest and propose go straight to the sidecar. check is the
three-step flow from module spec section 6: sidecar `prepare`, OwlTester's
reasoner, sidecar `findings`. propose only ever returns proposals; nothing it
says counts until a person confirms the term in the page.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import subprocess
from pathlib import Path

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


PROMPT_BIN = Path(__file__).resolve().parent / "prompt.mjs"
NO_KEY = ("Add your own OpenAI or Anthropic (Claude) key to have AI propose answers, "
          "or answer the questions yourself.")


def _payload(kind, terms, context, task):
    if kind == "task":
        return {"kind": "task", "task": task if isinstance(task, str) else ""}
    if kind == "terms":
        clean = [{"name": str(t.get("name"))[:80], "desc": str(t.get("desc") or "")[:300],
                  "hints": str(t.get("hints") or "")[:200]}
                 for t in (terms if isinstance(terms, list) else [])
                 if isinstance(t, dict) and t.get("name")]
        return {"kind": "terms", "terms": clean,
                "context": context if isinstance(context, str) else ""}
    if kind == "relations":
        clean = [{"name": str(t.get("name"))[:80], "kind": str(t.get("kind") or ""),
                  "desc": str(t.get("desc") or "")[:300]}
                 for t in (terms if isinstance(terms, list) else [])
                 if isinstance(t, dict) and t.get("name")]
        return {"kind": "relations", "terms": clean,
                "context": context if isinstance(context, str) else ""}
    raise sidecar.SidecarInputError('kind must be "task", "terms" or "relations".')


def _page_prompt(payload):
    """The prompt the page itself would send, from kindwork_core's builders."""
    return _prompt_bin(payload)["prompt"]


def _prompt_bin(payload):
    node = sidecar.node_bin()
    if not node:
        raise sidecar.SidecarError("Node.js is not installed on this server.")
    try:
        proc = subprocess.run([node, str(PROMPT_BIN)], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=sidecar.CALL_TIMEOUT,
                              check=False)
        reply = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        raise sidecar.SidecarError(f"prompt builder failed: {e}") from e
    if proc.returncode == 2:
        raise sidecar.SidecarInputError(reply.get("error") or "The input was refused.")
    if proc.returncode != 0:
        raise sidecar.SidecarError(reply.get("error") or "prompt builder failed")
    return reply


def _parse_reply(text):
    """Same tolerance as kindwork_core llm.js: bare JSON, a fenced block, or the outer braces."""
    t = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    for cand in (t, fence.group(1) if fence else None, t[t.find("{"):t.rfind("}") + 1]):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except ValueError:
            continue
    raise sidecar.SidecarUpstreamError(
        "The model answered in the wrong shape. Try again, or send fewer terms.", "invalid_json")


def _openai_propose(payload, key):
    from openai import OpenAI, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
    from openai_utils import OPENAI_MODEL
    prompt = _page_prompt(payload)
    try:
        resp = OpenAI(api_key=key, timeout=120).chat.completions.create(
            model=OPENAI_MODEL, max_tokens=8000, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt + "\n\nReply with the JSON only."}])
    except AuthenticationError as e:
        raise sidecar.SidecarUpstreamError(
            "Your OpenAI key was not accepted. Check it, or answer the questions yourself.",
            "invalid_key", 502) from e
    except RateLimitError as e:
        raise sidecar.SidecarUpstreamError(
            "Too many requests just now. Try again in a minute.", "rate_limited", 429) from e
    except APITimeoutError as e:
        raise sidecar.SidecarUpstreamError(
            "The model took too long. Try again with fewer terms.") from e
    except APIStatusError as e:
        raise sidecar.SidecarUpstreamError("The model could not be reached. Try again.") from e
    result = _parse_reply(resp.choices[0].message.content)
    if payload["kind"] == "relations":  # only relations the interview allows
        if not isinstance(result, dict) or not isinstance(result.get("relations"), list):
            raise sidecar.SidecarUpstreamError(
                "The model answered in the wrong shape. Try again, or send fewer terms.", "invalid_json")
        kept = _prompt_bin({"op": "relations", "terms": payload["terms"],
                            "relations": result["relations"]})["relations"]
        return {"result": {"relations": kept}, "model": OPENAI_MODEL}
    if not isinstance(result, dict) or not isinstance(result.get("terms"), list):
        raise sidecar.SidecarUpstreamError(
            "The model answered in the wrong shape. Try again, or send fewer terms.", "invalid_json")
    if payload["kind"] == "terms":  # drop any term the model invented
        asked = {t["name"].lower() for t in payload["terms"]}
        result["terms"] = [t for t in result["terms"]
                           if isinstance(t, dict) and str(t.get("name", "")).lower() in asked]
    return {"result": result, "model": OPENAI_MODEL}


def propose(kind, terms=None, context=None, task=None, ai=None):
    """Proposals only, on the visitor's own key: ai = (provider, key) or None.

    Anthropic keys go to the sidecar, which builds the prompt from the page and
    calls Claude. OpenAI keys get the same page-built prompt, sent from here.
    No key is a 503 sampling_disabled; server-side keys are never used.
    """
    payload = _payload(kind, terms, context, task)
    provider, key = ai or (None, None)
    if os.environ.get("KINDWORK_LLM_MOCK"):  # tests: the sidecar replays a fixed reply
        provider, key = "anthropic", key or ""
    if not provider:
        raise sidecar.SidecarUpstreamError(NO_KEY, "sampling_disabled", 503)
    if provider == "openai":
        return _openai_propose(payload, key)
    reply = sidecar.call("propose", timeout=PROPOSE_TIMEOUT,
                         env={"KINDWORK_LLM_KEY": key} if key else None, **payload)
    return {"result": reply.get("result"), "model": reply.get("model")}


def health():
    reply = sidecar.call("health")
    return {"ok": bool(reply.get("ok")), "core": reply.get("core"),
            "reasoner": dict(REASONER), "coreHash": sidecar.core_hash()}
