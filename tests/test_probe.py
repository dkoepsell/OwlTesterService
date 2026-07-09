"""Phase 2 of the coherence generalization (SPEC-coverage-coherence-demo.md §11):
satisfiability probes — can a named class have any instance at all?

probe_class must mirror the coverage demo's engine ordering (Prover9 decides
emptiness first; Mace4 only on the no-proof side) and return the Phase-1 proof
core when empty, or a decoded Mace4 witness when inhabited.
"""
import os
import shutil

import pytest

from fol_export import build_theory
from prover9_runner import _parse_interpretation, _witness_from_model, probe_class
from tests.conftest import fixture_path

requires_provers = pytest.mark.skipif(
    shutil.which("prover9") is None or shutil.which("mace4") is None,
    reason="prover9/mace4 binaries not on PATH")


@pytest.fixture(scope="module")
def straddle_theory():
    return build_theory(file_path=fixture_path("quality_disposition_straddle.owl"))


def _iri_for(theory, label):
    return next(iri for iri, rec in theory.classes.items()
                if rec["label"] == label)


# -- model decoding (no binaries needed) -----------------------------------------

_MODEL = """
interpretation( 2, [number=1, seconds=0], [
        function(disposition, [ 0 ]),
        function(force, [ 0 ]),
        function(quality, [ 1 ]),
        relation(instance_of(_,_,_), [
           0, 0,
           1, 0,
           0, 0,
           0, 0 ])
]).
"""


def test_parse_interpretation():
    dom, consts, rels = _parse_interpretation(_MODEL)
    assert dom == 2
    assert consts == {"disposition": 0, "force": 0, "quality": 1}
    arity, table = rels["instance_of"]
    assert arity == 3 and len(table) == 8 and table[2] == 1


def test_witness_decodes_memberships(straddle_theory):
    w = _witness_from_model(_MODEL, straddle_theory, "quality",
                            "continuant", align=False)
    assert w == {"memberships": ["quality"], "domain_size": 2}


def test_witness_none_on_garbage(straddle_theory):
    assert _witness_from_model("not a model", straddle_theory, "quality",
                               "continuant", align=False) is None


# -- probe engine -----------------------------------------------------------------

def test_probe_unknown_class(straddle_theory):
    assert probe_class(straddle_theory, "http://nope#Missing")["status"] == "unknown"


@requires_provers
def test_probe_empty_class_returns_core(straddle_theory):
    r = probe_class(straddle_theory, _iri_for(straddle_theory, "Force"))
    assert r["status"] == "empty"
    texts = [ax["text"] for ax in r["core"]["axioms"]]
    assert sorted(texts) == ["Force SubClassOf disposition",
                             "Force SubClassOf quality",
                             "disposition DisjointWith quality"]
    assert r["core"]["may_use_background"] is False
    assert "witness" not in r


@requires_provers
def test_probe_inhabited_class_returns_witness(straddle_theory):
    r = probe_class(straddle_theory, _iri_for(straddle_theory, "quality"))
    assert r["status"] == "inhabited"
    assert "quality" in r["witness"]["memberships"]
    assert "core" not in r
    assert r["engine"] == "prover9+mace4"


# -- the API route ------------------------------------------------------------------

@pytest.fixture()
def client():
    # conftest.py points DATABASE_URL at the suite-wide scratch database
    # before any test can import the app singleton.
    import app as app_module

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        app_module.db.create_all()
        yield flask_app.test_client()
        app_module.db.session.remove()


def _make_analysis(owl_name):
    from models import db, OntologyFile, OntologyAnalysis

    src = fixture_path(owl_name)
    file_record = OntologyFile(
        filename=owl_name, original_filename=owl_name, file_path=src,
        file_size=os.path.getsize(src), mime_type="application/rdf+xml")
    db.session.add(file_record)
    db.session.commit()
    analysis = OntologyAnalysis(ontology_file_id=file_record.id)
    db.session.add(analysis)
    db.session.commit()
    return analysis.id


@requires_provers
def test_probe_route_resolves_by_label(client):
    aid = _make_analysis("quality_disposition_straddle.owl")
    resp = client.post(f"/api/analysis/{aid}/probe", json={"class": "Force"})
    assert resp.status_code == 200
    r = resp.get_json()
    assert r["status"] == "empty"
    assert len(r["core"]["axioms"]) == 3


def test_probe_route_rejects_missing_class(client):
    aid = _make_analysis("quality_disposition_straddle.owl")
    assert client.post(f"/api/analysis/{aid}/probe", json={}).status_code == 400
    resp = client.post(f"/api/analysis/{aid}/probe", json={"class": "NoSuch"})
    assert resp.status_code == 404
