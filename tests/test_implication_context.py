"""AI implications are grounded in the ontology's own axioms, not placeholders."""

import io
import json

import pytest

from tests.test_ontology_bundle import client  # noqa: F401  (fixture)

TTL = """@prefix : <http://example.org/clinic#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .

<http://example.org/clinic> a owl:Ontology .
:Referral a owl:Class ; rdfs:subClassOf obo:BFO_0000031 ;
    obo:IAO_0000115 "A document by which a physician directs a patient to a specialist." .
:Specialist a owl:Class ; rdfs:subClassOf obo:BFO_0000040 .
:Nurse a owl:Class ; owl:disjointWith :Specialist .
:refersTo a owl:ObjectProperty ; rdfs:domain :Referral ; rdfs:range :Specialist .
obo:BFO_0000031 a owl:Class .
obo:BFO_0000040 a owl:Class .
obo:BFO_0000004 a owl:Class .
obo:BFO_0000040 rdfs:subClassOf obo:BFO_0000004 .
"""


@pytest.fixture()
def analysis(client):  # noqa: F811
    from models import OntologyAnalysis, OntologyFile
    resp = client.post("/upload", data={"file": (io.BytesIO(TTL.encode()), "clinic.ttl")},
                       content_type="multipart/form-data")
    stored = resp.headers["Location"].rsplit("/", 1)[-1].split("?")[0]
    client.get(f"/api/analyze/{stored}")
    record = OntologyFile.query.filter_by(filename=stored).one()
    return OntologyAnalysis.query.filter_by(ontology_file_id=record.id).one(), record


def test_context_has_domain_axioms_and_definitions(analysis):
    from implication_context import build_context
    a, record = analysis
    ctx = build_context(a, record.file_path)
    texts = [x["text"] for x in ctx["axioms"]]
    assert any("Nurse" in t and "Specialist" in t for t in texts)  # disjointness
    assert any("refersTo" in t for t in texts)                     # domain/range
    assert not any("BFO_0000040 ⊑" in t or "independent continuant ⊑" in t
                   for t in texts)  # BFO-only axiom dropped
    assert ctx["axioms"][0]["type"] == "DisjointWith"  # richest kinds first
    assert any("physician directs a patient" in d["text"] for d in ctx["definitions"])
    assert not any("BFO" in c for c in ctx["classes"])


def test_generation_prompt_and_citations(client, analysis, monkeypatch):  # noqa: F811
    import api_key_utils
    import openai_utils
    a, _ = analysis
    seen = {}

    def fake_call(system_prompt, user_prompt, api_key):
        seen["prompt"] = user_prompt
        return json.dumps({"implications": [
            {"title": "Nurses cannot receive referrals", "scenario": "s",
             "premises_used": ["A1", "A2"], "explanation": "e"},
            {"title": "Generic", "scenario": "s", "premises_used": ["common sense"],
             "explanation": "e"},
        ]})

    monkeypatch.setattr(api_key_utils, "resolve_ai", lambda: ("anthropic", "k"))
    monkeypatch.setattr(openai_utils, "_generate_implications_anthropic", fake_call)

    out = client.post(f"/api/analysis/{a.id}/implications").get_json()
    assert out["success"]
    assert "instance_of(x" not in seen["prompt"]  # no placeholder premises
    assert "A1 [DisjointWith]" in seen["prompt"]
    assert "physician directs a patient" in seen["prompt"]
    # The ungrounded implication is dropped; cited IDs resolve to axiom text.
    assert [i["title"] for i in out["implications"]] == ["Nurses cannot receive referrals"]
    assert out["implications"][0]["premises_used"][0].startswith("A1: ")
