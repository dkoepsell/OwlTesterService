"""UML view (vendored owl2uml): page, JSON SVG, and SVG download for a stored file."""

import io

import pytest

from tests.test_ontology_bundle import STACK, client  # noqa: F401  (fixture)


@pytest.fixture()
def stored(client):  # noqa: F811
    resp = client.post("/upload", data={"file": (io.BytesIO(STACK["patterns.ttl"].encode()), "one.ttl")},
                       content_type="multipart/form-data")
    assert resp.status_code == 302
    return resp.headers["Location"].rsplit("/", 1)[-1]


def test_uml_page_and_svg(client, stored):  # noqa: F811
    page = client.get(f"/analyze/{stored}/uml")
    assert page.status_code == 200 and b"uml-viewport" in page.data

    data = client.get(f"/analyze/{stored}/uml?format=json").get_json()
    assert "<svg" in data["svg"]
    assert data["classes"] >= 2  # A, B
    assert data["engine"] in ("graphviz", "builtin")

    svg = client.get(f"/analyze/{stored}/uml?format=svg")
    assert svg.mimetype == "image/svg+xml" and b"<svg" in svg.data


def test_bundle_upload_renders_merged_uml(client):  # noqa: F811
    data = {"file": [(io.BytesIO(t.encode()), n) for n, t in STACK.items()]}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    stored = resp.headers["Location"].rsplit("/", 1)[-1]
    out = client.get(f"/analyze/{stored}/uml?format=json").get_json()
    assert out["classes"] >= 4  # A, B (patterns), D (core), C (thesis)
