"""The HTTP surface for the recognition layer.

Route tests, plus the boundary validation CLAUDE.md asks for on user input:
filenames that try to escape the upload folder, records that are not records,
and loci that are not loci.
"""

import os
import shutil

import pytest

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "recognition")

ARTIFACT = "test_recognition_routes.ttl"


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("SESSION_SECRET", "test")
    from app import app

    upload_dir = app.config.get("UPLOADED_OWLS_DEST", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    target = os.path.join(upload_dir, ARTIFACT)
    shutil.copy(os.path.join(FIXTURES, "structural.ttl"), target)

    app.config["TESTING"] = True
    yield app.test_client()

    if os.path.exists(target):
        os.remove(target)


# --- reading ------------------------------------------------------------------

def test_json_report_is_served(client):
    response = client.get(f"/api/recognition/{ARTIFACT}?fast=1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["fingerprint"]["artifact_class"] == "recognition-only"
    assert body["measure"]["cd_corrected"] >= 0


def test_page_renders(client):
    response = client.get(f"/recognition/{ARTIFACT}?fast=1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Recognition layer" in html
    assert "What was assessed, and what was not" in html


def test_page_always_states_what_was_never_looked_for(client):
    """The coverage panel is not optional and must not be collapsible away."""
    html = client.get(f"/recognition/{ARTIFACT}?fast=1").get_data(as_text=True)
    assert "Absence of a flag is not evidence of absence" in html


def test_kernel_vocabulary_is_served(client):
    body = client.get("/api/recognition/kernel").get_json()
    assert len(body["kernel"]) == 12
    assert len(body["chain_loci"]) == 7
    assert len(body["classificatory_types"]) == 7
    assert len(body["system_classes"]) == 3


def test_missing_artifact_is_404(client):
    assert client.get("/api/recognition/does-not-exist.ttl").status_code == 404


def test_path_traversal_is_refused(client):
    for attempt in ("..%2f..%2fetc%2fpasswd", "..%2f..%2fapp.py"):
        assert client.get(f"/api/recognition/{attempt}").status_code == 404


# --- declaring a chain binding ------------------------------------------------

def test_bind_accepts_known_loci(client):
    response = client.post(f"/api/recognition/{ARTIFACT}/bind",
                           json={"http://example.org/rec#SeverityRating": "criteria"})
    assert response.status_code == 200
    assert response.get_json()["bound"] == 1


def test_bind_rejects_unknown_loci_by_name(client):
    body = client.post(f"/api/recognition/{ARTIFACT}/bind",
                       json={"http://example.org/x": "nonsense"}).get_json()
    assert body["bound"] == 0
    assert body["rejected"] == ["http://example.org/x"]


def test_bind_requires_an_object(client):
    assert client.post(f"/api/recognition/{ARTIFACT}/bind",
                       json=[1, 2]).status_code == 400


# --- attaching an institutional record ----------------------------------------

def test_record_accepts_a_well_formed_record(client):
    response = client.post(
        f"/api/recognition/{ARTIFACT}/record",
        json={"adjudications": [{"category": "X", "outcome": "contradicted"}]})
    assert response.status_code == 200


def test_record_rejects_a_malformed_record(client):
    assert client.post(f"/api/recognition/{ARTIFACT}/record",
                       json={"acts": "not a list"}).status_code == 400


def test_record_rejects_an_empty_body(client):
    """Regression: reading the stream uncached made every payload validate.

    ``get_data(cache=False)`` consumes the request stream, so the subsequent
    ``get_json()`` returned None and validation ran against nothing. Every
    malformed record was accepted with a 200.
    """
    assert client.post(f"/api/recognition/{ARTIFACT}/record",
                       data="").status_code == 400


def test_record_warns_about_unknown_keys(client):
    body = client.post(f"/api/recognition/{ARTIFACT}/record",
                       json={"provenance": "somewhere"}).get_json()
    assert any("provenance" in w for w in body["warnings"])


# --- declaring the object's system class --------------------------------------

def test_object_class_rejects_an_unknown_row(client):
    assert client.post(f"/api/recognition/{ARTIFACT}/object-class",
                       json={"object_class": "bogus"}).status_code == 400


def test_object_class_accepts_a_known_row(client):
    response = client.post(f"/api/recognition/{ARTIFACT}/object-class",
                           json={"object_class": "recognition-only"})
    assert response.status_code == 200
    assert response.get_json()["object_class"] == "recognition-only"
