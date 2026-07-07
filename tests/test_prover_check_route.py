"""The Prover9/Mace4 cross-check runs in the background for every analysis.

POST /api/analysis/<id>/prover-check must return immediately with a 'running'
marker (never block the request on per-class prover invocations), GET must poll
the stored verdict, and the auto-start hook must be idempotent while a run is
in flight. Works whether or not the prover9 binary is installed: without it the
worker still finishes quickly with ran=False and a clear reason.

Note: with the SQLite test database, the session that created the fixtures must
be released (db.session.remove()) before waiting on the worker — an idle read
transaction would lock the worker's commit out.
"""

import datetime
import os
import time

import pytest

from tests.conftest import fixture_path


@pytest.fixture()
def client(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path/'prover_route_test.db'}"
    import app as app_module

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        app_module.db.create_all()
        yield flask_app.test_client()
        app_module.db.session.remove()


def _make_analysis():
    """Create a file + analysis row and return the analysis id, releasing the
    session so the background worker can write."""
    from models import db, OntologyFile, OntologyAnalysis

    src = fixture_path("coherent_tiny.owl")
    file_record = OntologyFile(
        filename="coherent_tiny.owl",
        original_filename="coherent_tiny.owl",
        file_path=src,
        file_size=os.path.getsize(src),
        mime_type="application/rdf+xml",
    )
    db.session.add(file_record)
    db.session.commit()
    analysis = OntologyAnalysis(ontology_file_id=file_record.id)
    db.session.add(analysis)
    db.session.commit()
    analysis_id = analysis.id
    db.session.remove()
    return analysis_id


def _set_cross_check(analysis_id, value):
    from models import db, OntologyAnalysis

    analysis = db.session.get(OntologyAnalysis, analysis_id)
    analysis.prover_cross_check = value
    db.session.commit()
    db.session.remove()


def _wait_done(client, analysis_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        pc = client.get(f"/api/analysis/{analysis_id}/prover-check").get_json()
        if pc.get("status") == "done":
            return pc
        time.sleep(0.2)
    pytest.fail("prover cross-check did not reach status 'done' in time")


def test_get_without_result_reports_none(client):
    analysis_id = _make_analysis()
    resp = client.get(f"/api/analysis/{analysis_id}/prover-check")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "none"}


def test_post_starts_background_check_and_get_polls_verdict(client):
    analysis_id = _make_analysis()
    resp = client.post(f"/api/analysis/{analysis_id}/prover-check")
    assert resp.status_code == 202
    marker = resp.get_json()
    assert marker["status"] == "running"
    assert marker["ran"] is False
    assert marker["bfo_background"] is False

    pc = _wait_done(client, analysis_id)
    # With prover9 installed the check really ran; without it the worker must
    # still land on 'done' with a clear reason — never on a stuck marker.
    if pc["ran"]:
        assert "prover9" in pc["engine"]
        assert isinstance(pc["prover_unsatisfiable"], list)
    else:
        assert pc["reason"]
    assert pc["finished_at"]


def test_start_is_idempotent_while_running(client):
    import app as app_module
    from models import db, OntologyAnalysis

    analysis_id = _make_analysis()
    # A fresh 'running' marker must be returned as-is, not restarted.
    marker = {"ran": False, "status": "running", "bfo_background": False,
              "started_at": datetime.datetime.utcnow().isoformat()}
    _set_cross_check(analysis_id, marker)

    analysis = db.session.get(OntologyAnalysis, analysis_id)
    assert app_module.start_prover_check(analysis) == marker
    db.session.remove()

    resp = client.post(f"/api/analysis/{analysis_id}/prover-check")
    assert resp.status_code == 202
    assert resp.get_json()["started_at"] == marker["started_at"]


def test_stale_running_marker_is_reported_and_restartable(client):
    import app as app_module

    analysis_id = _make_analysis()
    stale_start = (datetime.datetime.utcnow()
                   - datetime.timedelta(seconds=app_module._PROVER_STALE_SECONDS + 60))
    _set_cross_check(analysis_id, {"ran": False, "status": "running",
                                   "bfo_background": False,
                                   "started_at": stale_start.isoformat()})

    pc = client.get(f"/api/analysis/{analysis_id}/prover-check").get_json()
    assert pc["status"] == "stale"

    # And a POST past the stale window starts a fresh run.
    resp = client.post(f"/api/analysis/{analysis_id}/prover-check")
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "running"
    _wait_done(client, analysis_id)
