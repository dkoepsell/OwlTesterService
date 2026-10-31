"""Section 9: conceptual lenses.

A lens is a file of the questions a reviewer asks of a domain. Each question
carries label patterns (regular expressions over labels and local names) and
optionally SPARQL; the audit fills a coverage table with the candidate terms
they find and marks every row ``proposed``. A reviewer confirms or rejects rows
on the report page before export; nothing is a finding until confirmed. An
optional AI draft of the rows uses only the visitor's own key.
"""

import json
import os
import re

from rdflib import OWL, RDF, RDFS, URIRef
from rdflib.namespace import SKOS

from .schema_checks import local, qname

LENS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lens_files")
STATUSES = ("proposed", "confirmed", "rejected", "no candidates")
MAX_CANDIDATES = 12


def available_lenses():
    return sorted(n[:-5] for n in os.listdir(LENS_DIR) if n.endswith(".json")) + ["sool"]


def load_lens(name):
    if name == "sool":
        return _sool_lens()
    path = os.path.join(LENS_DIR, f"{os.path.basename(name)}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sool_lens():
    """One question per SOoL kernel category: which artifact terms are kinds of it?"""
    from ..kernel import default_kernel_path, load_kernel
    kernel = load_kernel(default_kernel_path())
    questions = []
    for cat in sorted(kernel.categories, key=lambda c: c.label):
        words = [w for w in re.split(r"\W+", cat.label.lower()) if len(w) > 3]
        questions.append({"id": local(cat.iri), "group": "kernel", "node": cat.label,
                          "question": f"Which terms are kinds of {cat.label}?",
                          "label_patterns": words or [re.escape(cat.label.lower())]})
    return {"name": "sool", "title": "SOoL kernel categories", "questions": questions,
            "about": "Candidate terms for each SOoL kernel category, by label."}


def _terms(tbox):
    """Classes, properties and concepts with their display text."""
    kinds = (OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty, SKOS.Concept,
             SKOS.ConceptScheme)
    out = {}
    for k in kinds:
        for s in tbox.subjects(RDF.type, k):
            if isinstance(s, URIRef):
                labels = [str(lab) for lab in tbox.objects(s, RDFS.label)] + \
                    [str(lab) for lab in tbox.objects(s, SKOS.prefLabel)]
                name = re.sub(r"([a-z])([A-Z])", r"\1 \2", local(s))
                out[s] = {"text": " | ".join([name] + labels).lower(),
                          "label": labels[0] if labels else local(s)}
    return out


def fill(lens, art, tbox):
    terms = _terms(tbox)
    rows = []
    for q in lens["questions"]:
        hits = {}
        for pat in q.get("label_patterns", []):
            rx = re.compile(pat, re.I)
            for t, info in terms.items():
                if t not in hits and art.is_owned(t) and rx.search(info["text"]):
                    hits[t] = f"label matches /{pat}/"
        if q.get("sparql"):
            try:
                for row in tbox.query(q["sparql"]):
                    t = row[0]
                    if isinstance(t, URIRef) and t not in hits:
                        hits[t] = "SPARQL pattern"
            except Exception as e:  # noqa: BLE001 - a bad pattern in a lens file
                q = dict(q, sparql_error=str(e)[:200])
        cands = [{"iri": str(t), "term": qname(tbox, t), "label": terms.get(t, {}).get("label", local(t)),
                  "evidence": why} for t, why in sorted(hits.items(), key=lambda x: str(x[0]))]
        rows.append({"id": q["id"], "group": q.get("group", ""), "node": q["node"],
                     "question": q["question"], "candidates": cands[:MAX_CANDIDATES],
                     "more": max(0, len(cands) - MAX_CANDIDATES),
                     "status": "proposed" if cands else "no candidates",
                     "note": "", "source": "patterns"})
    return {"lens": lens["name"], "title": lens.get("title", lens["name"]),
            "about": lens.get("about", ""), "rows": rows}


def run_lenses(ctx):
    art = ctx.artifact
    tbox = art.tbox()
    if not len(tbox):
        return []
    out = []
    for name in ctx.profile.get("lenses", ()):
        try:
            out.append(fill(load_lens(name), art, tbox))
        except Exception as e:  # noqa: BLE001 - a lens never breaks an audit
            out.append({"lens": name, "title": name, "error": str(e)[:300], "rows": []})
    return out


def review(lenses, lens_name, row_id, status, note=""):
    """Apply a reviewer's decision to one row; returns the updated row."""
    if status not in ("proposed", "confirmed", "rejected"):
        raise ValueError("status must be proposed, confirmed or rejected")
    for lens in lenses:
        if lens.get("lens") != lens_name:
            continue
        for row in lens.get("rows", []):
            if row["id"] == row_id:
                row["status"] = status
                row["note"] = (note or "")[:1000]
                return row
    raise KeyError(f"no row {row_id!r} in lens {lens_name!r}")


def confirmed_rows(lenses):
    return [(lens, row) for lens in lenses for row in lens.get("rows", [])
            if row.get("status") == "confirmed"]


# -- optional AI draft (visitor's own key only) --------------------------------------

_SYSTEM = ("You review ontologies against a list of domain questions. For each question you "
           "receive the ontology terms a pattern search found. Reply with JSON "
           "{\"rows\": [{\"id\": ..., \"candidates\": [term, ...], \"note\": ...}]} keeping only "
           "terms that genuinely answer the question, and say in the note what is missing. Use "
           "only the given terms.")


def ai_draft(lens_table, ai):
    """Ask the visitor's model to refine candidate rows. ``ai`` is (provider, key)."""
    provider, key = ai
    payload = [{"id": r["id"], "question": r["question"],
                "candidates": [f"{c['term']} ({c['label']})" for c in r["candidates"]]}
               for r in lens_table["rows"]]
    user = json.dumps({"lens": lens_table["title"], "rows": payload})
    if provider == "anthropic":
        from openai_utils import _generate_implications_anthropic
        text = _generate_implications_anthropic(_SYSTEM, user, key)
    else:
        from openai_utils import OPENAI_MODEL, get_openai_client
        resp = get_openai_client(key).chat.completions.create(
            model=OPENAI_MODEL, messages=[{"role": "system", "content": _SYSTEM},
                                          {"role": "user", "content": user}],
            response_format={"type": "json_object"}, temperature=0.2)
        text = resp.choices[0].message.content
    m = re.search(r"\{.*\}", text or "", re.S)
    drafted = json.loads(m.group(0)).get("rows", []) if m else []
    by_id = {r["id"]: r for r in lens_table["rows"]}
    for d in drafted:
        row = by_id.get(d.get("id"))
        if row is None or row["status"] in ("confirmed", "rejected"):
            continue
        keep = {str(t).split(" (")[0] for t in d.get("candidates", [])}
        row["candidates"] = [c for c in row["candidates"] if c["term"] in keep]
        row["note"] = str(d.get("note", ""))[:1000]
        row["source"] = "AI draft"
        row["status"] = "proposed" if row["candidates"] else "no candidates"
    return lens_table
