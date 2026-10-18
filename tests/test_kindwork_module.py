"""Acceptance tests for the Kindwork module (SPEC-OWLTESTER-KINDWORK-MODULE.md, section 10).

A1 to A11 are the reference tests in kindwork_core/test, run here through Node.
B1 to B9 exercise OwlTester's routes, reasoner pipeline and MCP endpoint.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "kindwork_core"
FIX = CORE / "test" / "fixtures"
EM_DASH = "—"
A2_SOURCE = ('app "Bad"\nstatuss "License"\nhappening "Inspection"\n  held_by "Worker"\n'
             'thing "Worker"\nstatus "Permit"\n  issued_by "Worker"\n  bearer "Inspection"\n'
             '  held_by "Nobody"')
NOTATION = re.compile(r"SubClassOf|BFO_|owl:|rdfs:|https?://")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (CORE / "node_modules").is_dir(),
    reason="kindwork_core needs Node and `npm ci`")
needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="reasoner needs Java")


def fx(name):
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture()
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    return app_module.app.test_client()


def post(client, op, source, name, **headers):
    return client.post(f"/kindwork/v1/{op}", json={"source": source, "name": name}, headers=headers)


# --- reference tests -----------------------------------------------------------

@needs_node
def test_reference_acceptance_a1_to_a11():
    proc = subprocess.run(["node", "--test", "--test-reporter=tap", "test/acceptance.test.js"],
                          cwd=CORE, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    assert "# fail 0" in proc.stdout


# --- B1, B2: build -----------------------------------------------------------------

@needs_node
def test_b1_build_zip_has_six_files_under_slug(client):
    resp = post(client, "build", fx("job-site-tracker.kw"), "job-site-tracker.kw",
                Accept="application/zip")
    assert resp.status_code == 200 and resp.mimetype == "application/zip"
    names = sorted(zipfile.ZipFile(io.BytesIO(resp.data)).namelist())
    assert names == sorted(f"job-site-tracker/{n}" for n in [
        "README.md", "job-site-tracker-shapes.ttl", "job-site-tracker.html",
        "job-site-tracker.kindwork.json", "job-site-tracker.kw", "job-site-tracker.ttl"])


@needs_node
def test_b2_build_errors_are_422_with_five_diagnostics(client):
    resp = post(client, "build", A2_SOURCE, "bad.kw")
    assert resp.status_code == 422
    errors = resp.get_json()["errors"]
    assert sorted(d["line"] for d in errors) == [2, 4, 7, 8, 9]
    by = {d["line"]: d["message"] for d in errors}
    assert "Did you mean status?" in by[2]
    assert '"Nobody" isn\'t defined in this file' in by[9]
    assert resp.headers["X-Kindwork-Core"]


# --- B3 to B5: check through OwlTester's pipeline --------------------------------

@needs_node
@needs_java
def test_b3_check_straddle_finds_partition_and_within(client):
    resp = post(client, "check", fx("straddle-imports-bfo.ttl"), "straddle.ttl")
    assert resp.status_code == 200
    doc = resp.get_json()
    assert doc["verdict"] == {"consistent": True, "coherent": False}
    coh = [f for f in doc["findings"] if f["check"] == "coherence"]
    assert sorted(f["severity"] for f in coh) == ["partition", "within"]
    for f in coh:
        assert f["axioms"] and all("](" not in a and "http" not in a for a in f["axioms"])
        assert not NOTATION.search(f["title"] + f["explanation"])
    part = next(f for f in coh if f["severity"] == "partition")
    assert part["classes"] == ["http://ex.org/x#Episode"]
    assert "continuant DisjointWith occurrent" in part["axioms"]
    assert doc["reasoner"]["name"] == "HermiT"


@needs_node
@needs_java
def test_b4_check_tracker_model(client):
    resp = post(client, "check", fx("job-site-tracker.kindwork.json"), "job-site-tracker.kindwork.json")
    doc = resp.get_json()
    assert doc["verdict"] == {"consistent": True, "coherent": True}
    assert sorted(f["severity"] for f in doc["findings"]) == ["chain", "chain", "partition"]


@needs_node
def test_b5_forced_timeout_is_undetermined_not_500(client, monkeypatch):
    monkeypatch.setenv("KINDWORK_REASONER_TIMEOUT_MS", "1")
    resp = post(client, "check", fx("straddle-imports-bfo.ttl"), "straddle.ttl")
    assert resp.status_code == 200
    doc = resp.get_json()
    assert doc["verdict"] == {"consistent": None, "coherent": None}
    assert doc["findings"][0]["verdict"] == "undetermined"
    assert all(f["verdict"] != "pass" for f in doc["findings"])


# --- B6: MCP ---------------------------------------------------------------------------

def rpc(client, method, params=None, mid=1):
    return client.post("/kindwork/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method,
                                               "params": params or {}},
                       headers={"Accept": "application/json, text/event-stream"})


@needs_node
def test_b6_mcp_lists_four_tools_and_lint_reports_input_errors(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}).get_json()
    assert init["result"]["capabilities"]["tools"] is not None
    note = client.post("/kindwork/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
    tools = rpc(client, "tools/list").get_json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == [
        "kindwork_build", "kindwork_check", "kindwork_import", "kindwork_lint"]
    res = rpc(client, "tools/call", {"name": "kindwork_lint",
                                     "arguments": {"source": A2_SOURCE, "name": "bad.kw"}}).get_json()
    assert "error" not in res and res["result"]["isError"] is True
    body = json.loads(res["result"]["content"][0]["text"])
    assert body["errors"][0]["line"] == 2


def test_mcp_unknown_method_is_jsonrpc_error(client):
    assert rpc(client, "nope").get_json()["error"]["code"] == -32601


# --- B7: no em-dash ----------------------------------------------------------------

def test_b7_module_text_has_no_em_dash(client):
    paths = [*(ROOT / "kindwork").glob("*.py"), ROOT / "kindwork" / "vocab.ttl",
             ROOT / "templates" / "kindwork.html", *(CORE / "docs").glob("*.md"),
             *(CORE / "src").glob("*.js"), CORE / "bin" / "kindwork-core.mjs"]
    for p in paths:
        assert EM_DASH not in p.read_text(encoding="utf-8"), p
    assert EM_DASH not in client.get("/kindwork").get_data(as_text=True)


@needs_node
def test_b7_route_replies_have_no_em_dash(client):
    for op, src, name in [("lint", fx("job-site-tracker.kw"), "m.kw"),
                          ("build", fx("job-site-tracker.kw"), "m.kw"),
                          ("import", fx("straddle.ttl"), "straddle.ttl"),
                          ("build", A2_SOURCE, "bad.kw")]:
        assert EM_DASH not in post(client, op, src, name).get_data(as_text=True), op


# --- B8: body limit -------------------------------------------------------------------

def test_b8_nine_mb_body_is_413(client):
    big = json.dumps({"source": "x" * (9 * 1024 * 1024), "name": "big.kw"})
    resp = client.post("/kindwork/v1/build", data=big, content_type="application/json")
    assert resp.status_code == 413


# --- B9: findings link back to the terms Kindwork imports ----------------------------

@needs_node
@needs_java
def test_b9_findings_classes_are_kindwork_term_iris(client):
    doc = post(client, "check", fx("straddle-imports-bfo.ttl"), "straddle.ttl").get_json()
    model = post(client, "import", fx("straddle-imports-bfo.ttl"), "straddle.ttl").get_json()["model"]
    iris = {t["iri"] for t in model["terms"]}
    coh = [f for f in doc["findings"] if f["check"] == "coherence"]
    assert len(coh) == 2 and all(f["classes"][0] in iris for f in coh)


# --- other route behavior ---------------------------------------------------------------

@needs_node
def test_health_and_core_header(client):
    resp = client.get("/kindwork/v1/health")
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{12}", resp.headers["X-Kindwork-Core"])


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("KINDWORK_TOKEN", "s3cret")
    assert post(client, "lint", "thing \"X\"", "m.kw").status_code == 401
    assert client.get("/kindwork/v1/health").status_code in (200, 503)


def test_non_json_body_is_422(client):
    resp = client.post("/kindwork/v1/lint", data="nope", content_type="text/plain")
    assert resp.status_code == 422
