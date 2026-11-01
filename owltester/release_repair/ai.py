"""Optional AI pre-fill (spec 4.4), with the visitor's own key only.

The model sees only the snippets a card needs (the term, its label, the choices),
never the release. Its answer is returned as a suggestion; the user must accept
it, and the decision then records ``ai_assisted: true``.
"""

import json
import re

SYSTEM = ("You help repair an RDF/OWL release. Answer only with JSON. Never invent IRIs: "
          "choose from the options given, or write Turtle that uses only the prefixes given.")


def _complete(ai, system, user):
    provider, key = ai
    if provider == "anthropic":
        from openai_utils import _generate_implications_anthropic
        return _generate_implications_anthropic(system, user, key)
    from openai_utils import OPENAI_MODEL, get_openai_client
    resp = get_openai_client(key).chat.completions.create(
        model=OPENAI_MODEL, messages=[{"role": "system", "content": system},
                                      {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.2)
    return resp.choices[0].message.content


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else {}


def suggest(remedy, option, ai, complete=None):
    """{"values": {...}} for tables, {"value": text} for drafts. Nothing is applied."""
    complete = complete or _complete
    spec = option.input or {}
    kind = spec.get("kind")
    if kind == "table" and spec.get("choices"):
        rows = [{"row": i, "instance": r.get("subject"), "label": r.get("label", "")}
                for i, r in enumerate(spec.get("rows", [])[:150])]
        choices = [{"iri": c["iri"], "label": c["label"]} for c in spec["choices"]]
        user = json.dumps({"task": "Pick the most specific class for each instance, or null if "
                                   "none fits. Reply {\"values\": {\"<row>\": \"<iri or null>\"}}.",
                           "choices": choices, "rows": rows})
        allowed = {c["iri"] for c in choices}
        values = (_json(complete(ai, SYSTEM, user)).get("values") or {})
        return {"values": {str(k): v for k, v in values.items() if v in allowed}}
    if kind in ("turtle", "example"):
        user = json.dumps({"task": "Improve this draft so it is complete and correct. Reply "
                                   "{\"value\": \"<turtle>\"}.",
                           "card": remedy.title, "why": remedy.rationale,
                           "details": (remedy.explanation or "")[:3000],
                           "draft": str(spec.get("default", ""))[:6000]})
        return {"value": str(_json(complete(ai, SYSTEM, user)).get("value") or "")}
    raise ValueError("this card has nothing an AI can draft")
