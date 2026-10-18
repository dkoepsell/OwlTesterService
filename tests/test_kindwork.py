"""Acceptance tests for the Kindwork adapter (KINDWORK-ECOSYSTEM-SPEC.md, sections 4, 5, 8).

The reasoner-backed tests need Java; they skip when it is absent.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from kindwork import check_bundle, load_bundle
from kindwork.bundle import BundleRefused
from kindwork.findings import NotationError, make_finding

FIX = Path(__file__).resolve().parent / "fixtures" / "kindwork"
TRACKER = ["job-site-tracker.ttl", "job-site-tracker-shapes.ttl", "job-site-tracker.kindwork.json"]

needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="reasoner needs Java")


def _files(*names):
    return [(n, (FIX / n).read_bytes()) for n in names]


def _shape_keys(obj):
    """The nested key structure of a findings document, ignoring values."""
    if isinstance(obj, dict):
        return {k: _shape_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shape_keys(obj[0])] if obj else []
    return None


# --- bundle loading -------------------------------------------------------

def test_tracker_bundle_loads_all_three():
    b = load_bundle(_files(*TRACKER))
    assert b.slug == "job-site-tracker"
    assert b.shapes is not None
    assert b.manifest["format"] == "kindwork-model"
    assert b.label_for("https://example.org/kindwork/job-site-tracker#ElectricalLicense") == "Electrical license"


def test_bundle_from_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in _files(*TRACKER):
            z.writestr(name, data)
    b = load_bundle([("job-site-tracker.zip", buf.getvalue())])
    assert b.slug == "job-site-tracker"
    assert b.shapes is not None and b.manifest is not None


def test_functional_syntax_refused():
    ofn = b"Prefix(:=<http://ex.org/x#>)\nOntology(<http://ex.org/x>\nDeclaration(Class(:A))\n)\n"
    with pytest.raises(BundleRefused):
        load_bundle([("x.ofn", ofn)])


def test_label_falls_back_to_rdfs_label_then_local_name():
    b = load_bundle(_files("straddle.ttl"))
    assert b.label_for("http://ex.org/x#Episode") == "Manic episode"
    assert b.label_for("http://ex.org/x#Nowhere") == "Nowhere"


# --- findings format hard stops -------------------------------------------

def test_notation_rejected_in_title():
    with pytest.raises(NotationError):
        make_finding("coh-001", "coherence", "within", "fail", [], "A ⊑ B", "plain words", [])


def test_notation_rejected_in_explanation():
    with pytest.raises(NotationError):
        make_finding("coh-001", "coherence", "within", "fail", [], "plain", "A SubClassOf B", [])


def test_undetermined_never_pass_when_reasoner_does_not_finish():
    doc = check_bundle(load_bundle(_files("straddle.ttl")), reasoner_budget=0.001)
    assert doc["verdict"]["consistent"] is None
    # The asserted straddles settle coherence without the reasoner.
    assert doc["verdict"]["coherent"] is False
    assert all(f["verdict"] != "pass" for f in doc["findings"])
    assert any(f["check"] == "consistency" and f["verdict"] == "undetermined" for f in doc["findings"])


# --- acceptance fixtures (section 8) ---------------------------------------

@needs_java
def test_straddle_fixture():
    doc = check_bundle(load_bundle(_files("straddle.ttl")))
    assert doc["verdict"] == {"consistent": True, "coherent": False}
    coh = {f["classes"][0]: f for f in doc["findings"] if f["check"] == "coherence"}
    episode, score = coh["http://ex.org/x#Episode"], coh["http://ex.org/x#Score"]
    assert (episode["severity"], episode["verdict"]) == ("partition", "fail")
    assert (score["severity"], score["verdict"]) == ("within", "fail")
    assert "Manic episode" in episode["title"]
    assert "written record" in score["title"]
    assert any("IAO_0000030" in a for a in score["axioms"])
    assert len(coh) == 2


@needs_java
def test_straddle_output_matches_sample_shape():
    doc = check_bundle(load_bundle(_files("straddle.ttl")))
    sample = json.loads((FIX / "findings-sample.json").read_text())
    assert _shape_keys(doc) == _shape_keys(sample)
    assert doc["format"] == "owltester-findings" and doc["version"] == "0.1"
    assert doc["ontology"] == sample["ontology"]
    note = [f for f in doc["findings"] if f["classes"] == ["http://ex.org/x#Note"]]
    assert note and note[0]["check"] == "entailment" and note[0]["verdict"] == "undetermined"


@needs_java
def test_tracker_fixture():
    doc = check_bundle(load_bundle(_files(*TRACKER)))
    assert doc["verdict"] == {"consistent": True, "coherent": True}
    chain = [f for f in doc["findings"] if f["check"] == "chain"]
    assert sorted(f["classes"][0].rsplit("#", 1)[1] for f in chain) == [
        "DutyToNotifyTheCity", "ElectricalLicense"]
    assert all(f["severity"] == "chain" and f["verdict"] == "fail" for f in chain)
    assert not [f for f in doc["findings"] if f["verdict"] == "fail" and f["check"] != "chain"]
    lic = next(f for f in chain if f["classes"][0].endswith("ElectricalLicense"))
    assert "Electrical license" in lic["title"]


@needs_java
def test_class_iris_pass_through_unchanged():
    doc = check_bundle(load_bundle(_files(*TRACKER)))
    src = (FIX / "job-site-tracker.ttl").read_text()
    for f in doc["findings"]:
        for iri in f["classes"]:
            assert iri.split("#", 1)[1] in src


# --- chain checks without the reasoner ------------------------------------

CLOSED_CHAIN = b"""
@prefix : <http://ex.org/c#> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . @prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix kwv: <https://ontology.davidkoepsell.com/kindwork/vocab#> .
<http://ex.org/c> a owl:Ontology .
:Auth a owl:Class ; kwv:keyword "authority" ; rdfs:subClassOf obo:BFO_0000023 ,
  [ a owl:Restriction ; owl:onProperty kwv:canGrant ; owl:someValuesFrom :Lic ] .
:Lic a owl:Class ; kwv:keyword "status" ; rdfs:subClassOf obo:BFO_0000031 ,
  [ a owl:Restriction ; owl:onProperty kwv:issuedBy ; owl:someValuesFrom :Auth ] .
:Half a owl:Class ; kwv:keyword "status" ; rdfs:subClassOf obo:BFO_0000031 ,
  [ a owl:Restriction ; owl:onProperty kwv:issuedBy ; owl:someValuesFrom :Auth ] .
:Duty a owl:Class ; kwv:keyword "obligation" ; rdfs:subClassOf obo:BFO_0000031 ,
  [ a owl:Restriction ; owl:onProperty kwv:owedTo ; owl:someValuesFrom :Auth ] .
"""


def test_chain_checks_closed_and_half_open():
    from kindwork.chain import chain_findings
    b = load_bundle([("c.ttl", CLOSED_CHAIN)])
    found = {f["classes"][0].rsplit("#", 1)[1]: f for f in chain_findings(b)}
    assert set(found) == {"Half"}
    assert "Auth" in found["Half"]["explanation"]


# --- conformance (SHACL) ---------------------------------------------------

ABOX = b"""
@prefix : <https://example.org/kindwork/job-site-tracker#> .
@prefix kwv: <https://ontology.davidkoepsell.com/kindwork/vocab#> .
:lic1 a :ElectricalLicense ; kwv:grantedOn "2026-01-01" .
"""


def test_conformance_findings_from_shapes():
    from kindwork.conformance import conformance_findings
    files = _files(*TRACKER) + [("job-site-tracker-data.ttl", ABOX)]
    b = load_bundle(files)
    found = conformance_findings(b)
    titles = {f["title"] for f in found}
    assert "Every Electrical license needs a name or reference." in titles
    assert "Held by must be a Worker, and is required." in titles
    assert all(f["check"] == "conformance" and f["verdict"] == "fail" for f in found)
    assert all(f["classes"] == ["https://example.org/kindwork/job-site-tracker#ElectricalLicense"] for f in found)


def test_no_abox_no_conformance_findings():
    from kindwork.conformance import conformance_findings
    assert conformance_findings(load_bundle(_files(*TRACKER))) == []


# --- routes ------------------------------------------------------------------

@pytest.fixture()
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    return app_module.app.test_client()


def test_route_refuses_empty_upload(client):
    resp = client.post("/kindwork/check", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400 and "error" in resp.get_json()


def test_route_refuses_functional_syntax(client):
    data = {"files": (io.BytesIO(b"Prefix(:=<http://ex.org/x#>)\nOntology()"), "x.ofn")}
    resp = client.post("/kindwork/check", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400 and "Turtle" in resp.get_json()["error"]


@needs_java
def test_route_returns_findings_download(client):
    data = {"files": [(io.BytesIO((FIX / n).read_bytes()), n) for n in TRACKER]}
    resp = client.post("/kindwork/check", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert 'filename="job-site-tracker.findings.json"' in resp.headers["Content-Disposition"]
    assert resp.get_json()["format"] == "owltester-findings"


def test_vocab_served_as_turtle(client):
    import rdflib
    resp = client.get("/kindwork/vocab")
    assert resp.status_code == 200 and resp.mimetype == "text/turtle"
    g = rdflib.Graph().parse(data=resp.data, format="turtle")
    kwv = rdflib.Namespace("https://ontology.davidkoepsell.com/kindwork/vocab#")
    for term in ("keyword", "issuedBy", "canGrant", "owedTo", "heldBy"):
        assert (kwv[term], None, None) in g


def test_page_renders(client):
    assert client.get("/kindwork").status_code == 200
