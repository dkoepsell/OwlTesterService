"""An ontology in a user's history is visible to that user and no one else.

Every route that reads, analyzes, exports, modifies or deletes a stored file or
analysis must answer 404 for someone else's -- the same as for a file that does
not exist -- and /history must list only the visitor's own files.
"""

import io
import os
import shutil
import uuid

import pytest

from tests.conftest import fixture_path, grant_anon_files

OWL = "coherent_tiny.owl"


@pytest.fixture()
def env():
    import app as app_module
    from models import db, User, OntologyFile, OntologyAnalysis, SandboxOntology

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    upload_dir = flask_app.config["UPLOADED_OWLS_DEST"]
    created_paths = []

    with flask_app.app_context():
        db.create_all()
        tag = uuid.uuid4().hex[:8]

        def make_user(name):
            user = User(username=f"{name}-{tag}", email=f"{name}-{tag}@example.org")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            return user.id

        def make_file(owner_id, label):
            filename = f"{uuid.uuid4().hex}.owl"
            path = os.path.join(upload_dir, filename)
            shutil.copy(fixture_path(OWL), path)
            created_paths.append(path)
            record = OntologyFile(filename=filename, original_filename=f"{label}-{tag}.owl",
                                  file_path=path, file_size=os.path.getsize(path),
                                  mime_type="application/rdf+xml", user_id=owner_id)
            db.session.add(record)
            db.session.commit()
            analysis = OntologyAnalysis(ontology_file_id=record.id)
            db.session.add(analysis)
            db.session.commit()
            return {"id": record.id, "filename": filename, "label": record.original_filename,
                    "analysis_id": analysis.id}

        alice, bob = make_user("alice"), make_user("bob")
        sandbox = SandboxOntology(title="bob sandbox", domain="d", subject="s", user_id=bob)
        db.session.add(sandbox)
        db.session.commit()
        data = {
            "app": flask_app,
            "alice": alice, "bob": bob,
            "alice_file": make_file(alice, "alice-secret"),
            "bob_file": make_file(bob, "bob-secret"),
            "bob_sandbox": sandbox.id,
        }
        db.session.remove()

    yield data

    for path in created_paths:
        if os.path.exists(path):
            os.remove(path)


def _client_as(env, user_key=None):
    client = env["app"].test_client()
    if user_key:
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env[user_key])
            sess["_fresh"] = True
    return client


def _file_exists(env, file_id):
    from models import db, OntologyFile
    with env["app"].app_context():
        return db.session.get(OntologyFile, file_id) is not None


def _read_routes(f):
    name, aid = f["filename"], f["analysis_id"]
    return [
        f"/download/{name}",
        f"/analyze/{name}",
        f"/analyze/{name}/report",
        f"/api/analyze/{name}",
        f"/implications/{name}",
        f"/analyze/{name}/diagram",
        f"/api/diagram-data/{name}",
        f"/analyze/{name}/uml",
        f"/analyze/{name}/bvss",
        f"/api/bvss/{name}",
        f"/api/validate-bvss/{name}",
        f"/api/bundle/{name}/layers",
        f"/recognition/{name}?fast=1",
        f"/api/recognition/{name}?fast=1",
        f"/shacl/{name}",
        f"/api/shacl/{name}/shapes",
        f"/api/analysis/{aid}/validate-completeness",
        f"/api/analysis/{aid}/check-enhanced-consistency",
        f"/api/analysis/{aid}/fol-export",
        f"/api/analysis/{aid}/prover-check",
        f"/api/analysis/{aid}/implications",
        f"/api/analysis/{aid}/fix-straddle",
        f"/api/analysis/{aid}/auto-fix-straddles",
    ]


def test_history_lists_only_own_files(env):
    html = _client_as(env, "alice").get("/history").get_data(as_text=True)
    assert env["alice_file"]["label"] in html
    assert env["bob_file"]["label"] not in html


def test_anonymous_history_shows_no_one_elses_files(env):
    html = _client_as(env).get("/history").get_data(as_text=True)
    assert env["alice_file"]["label"] not in html
    assert env["bob_file"]["label"] not in html


@pytest.mark.parametrize("who", ["alice", None])
def test_other_users_file_is_404_everywhere(env, who):
    client = _client_as(env, who)
    for url in _read_routes(env["bob_file"]):
        assert client.get(url).status_code == 404, url
    f = env["bob_file"]
    for url in (f"/analyze/{f['filename']}/reanalyze",
                f"/analysis/{f['analysis_id']}/fix-and-reanalyze",
                f"/analysis/{f['analysis_id']}/auto-fix-and-reanalyze",
                f"/api/analysis/{f['analysis_id']}/probe",
                f"/import_to_sandbox/{f['id']}",
                f"/delete_file/{f['id']}"):
        assert client.post(url).status_code == 404, url
    assert _file_exists(env, f["id"])


def test_bulk_delete_skips_other_users_files(env):
    client = _client_as(env, "alice")
    client.post("/delete_files", data={"file_ids": [str(env["bob_file"]["id"]),
                                                    str(env["alice_file"]["id"])]})
    assert _file_exists(env, env["bob_file"]["id"])
    assert not _file_exists(env, env["alice_file"]["id"])


def test_owner_can_read_own_file(env):
    client = _client_as(env, "bob")
    f = env["bob_file"]
    assert client.get(f"/download/{f['filename']}").status_code == 200
    assert client.get(f"/api/analysis/{f['analysis_id']}/prover-check").status_code == 200
    assert client.get(f"/shacl/{f['filename']}").status_code == 200


def test_other_users_sandbox_is_404(env):
    client = _client_as(env, "alice")
    sid = env["bob_sandbox"]
    for url in (f"/sandbox/{sid}", f"/sandbox/{sid}/edit", f"/sandbox/{sid}/download",
                f"/api/sandbox/{sid}/classes"):
        assert client.get(url).status_code == 404, url
    assert "bob sandbox" not in client.get("/sandbox").get_data(as_text=True)


def test_gate_refuses_paths_to_other_users_files(env):
    client = _client_as(env, "alice")
    resp = client.post("/owltester/check", json={"path": env["bob_file"]["filename"]})
    assert resp.status_code == 400
    resp = client.post("/owltester/check", json={"path": "/etc/passwd"})
    assert resp.status_code == 400


def test_anonymous_upload_is_private_to_its_session_and_claimed_on_login(env):
    with open(fixture_path(OWL), "rb") as fh:
        payload = fh.read()
    anon = _client_as(env)
    resp = anon.post("/upload", data={"file": (io.BytesIO(payload), "anon-upload.owl")},
                     content_type="multipart/form-data")
    assert resp.status_code == 302
    stored = resp.headers["Location"].rsplit("/", 1)[-1]
    try:
        assert anon.get(f"/download/{stored}").status_code == 200
        # A different anonymous visitor and a signed-in user cannot see it.
        assert _client_as(env).get(f"/download/{stored}").status_code == 404
        assert _client_as(env, "alice").get(f"/download/{stored}").status_code == 404

        # Logging in hands the anonymous upload to the account.
        from ownership import claim_anonymous_records
        from models import db, OntologyFile, User
        with env["app"].test_request_context():
            from flask import session
            with anon.session_transaction() as sess:
                session.update(sess)
            claim_anonymous_records(db.session.get(User, env["alice"]))
            assert OntologyFile.query.filter_by(filename=stored).first().user_id == env["alice"]
        assert _client_as(env, "alice").get(f"/download/{stored}").status_code == 200
    finally:
        path = os.path.join(env["app"].config["UPLOADED_OWLS_DEST"], stored)
        if os.path.exists(path):
            os.remove(path)


def test_anonymous_visitor_only_sees_granted_ids(env):
    client = _client_as(env)
    grant_anon_files(client, env["bob_file"]["id"])  # owned by bob, not anonymous
    assert client.get(f"/download/{env['bob_file']['filename']}").status_code == 404
