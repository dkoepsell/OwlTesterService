"""Route tests for the Kindwork module (SPEC-OWLTESTER-KINDWORK-MODULE.md 0.2.0, section 12).

A1 to A19 are the reference tests in kindwork_core/test, run here through Node.
B1, B4, B5, B7 to B13 are route-level here; B2, B3 and the page halves of B6 to B8
are browser tests in test_kindwork_ui.py.
"""

from __future__ import annotations

import base64
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
INGEST = FIX / "ingest"
EM_DASH = "\u2014"
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
def app_module(monkeypatch):
    import app as app_module
    monkeypatch.delenv("KINDWORK_MODE", raising=False)
    monkeypatch.delenv("KINDWORK_TOKEN", raising=False)
    for k in ("KINDWORK_LLM_KEY", "ANTHROPIC_API_KEY", "SOOL_ANTHROPIC_KEY", "KINDWORK_LLM_MOCK"):
        monkeypatch.delenv(k, raising=False)
    app_module.app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    return app_module


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture()
def mock_llm(monkeypatch):
    monkeypatch.setenv("KINDWORK_LLM_MOCK", str(INGEST / "mock-proposal.json"))


def post(client, op, body, **headers):
    return client.post(f"/kindwork/v1/{op}", json=body, headers=headers)


def src(client, op, source, name, **headers):
    return post(client, op, {"source": source, "name": name}, **headers)


def claims_terms():
    lines = (INGEST / "claims-terms.csv").read_text(encoding="utf-8").strip().splitlines()[1:]
    return [{"name": ln.split(",", 1)[0].strip('"')} for ln in lines]


# --- reference tests ------------------------------------------------------------

@needs_node
def test_reference_acceptance_a1_to_a19():
    proc = subprocess.run(["node", "--test", "--test-reporter=tap", "test/acceptance.test.js"],
                          cwd=CORE, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    assert "# fail 0" in proc.stdout
    passed = int(re.search(r"# pass (\d+)", proc.stdout).group(1))
    skipped = int(re.search(r"# skipped (\d+)", proc.stdout).group(1))
    assert passed + skipped == 19 and skipped <= 1  # A11 skips only without ROBOT


# --- B1: the page ------------------------------------------------------------------

def _host(html):
    return json.loads(re.search(r"window\.KINDWORK_HOST = (\{.*?\});", html).group(1))


def test_b1_page_has_one_host_script_before_the_page_scripts(client, monkeypatch):
    html = client.get("/kindwork").get_data(as_text=True)
    assert html.count("<script>window.KINDWORK_HOST =") == 1
    meta = html.index('<meta name="claude:viewport-fit-sides" content="cover">')
    injected = html.index("<script>window.KINDWORK_HOST =")
    assert injected > meta
    assert injected < html.index("<script", meta + 1) + 1  # it is the first script after the meta
    assert all(i >= injected for i in [m.start() for m in re.finditer(r"<script", html)])
    assert _host(html) == {"api": "/kindwork/v1", "mode": "triage"}
    page = (CORE / "core" / "kindwork.html").read_text(encoding="utf-8")
    assert html.replace(html[injected:html.index("</script>", injected) + len("</script>\n")], "") == page


def test_b1_full_mode_requires_sign_in(client, monkeypatch):
    monkeypatch.setenv("KINDWORK_MODE", "full")
    resp = client.get("/kindwork")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert src(client, "lint", 'thing "X"', "m.kw").status_code == 401


def test_b1_full_mode_with_token(client, monkeypatch):
    monkeypatch.setenv("KINDWORK_MODE", "full")
    monkeypatch.setenv("KINDWORK_TOKEN", "s3cret")
    resp = client.get("/kindwork", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200 and _host(resp.get_data(as_text=True))["mode"] == "full"


def test_b1_cta_from_environment(client, monkeypatch):
    for k, v in {"TITLE": "Talk to us", "TEXT": "We check it.", "HREF": "https://example.org/t",
                 "LABEL": "Book it"}.items():
        monkeypatch.setenv(f"KINDWORK_CTA_{k}", v)
    assert _host(client.get("/kindwork").get_data(as_text=True))["cta"]["label"] == "Book it"


# --- ingest and propose ---------------------------------------------------------------

@needs_node
def test_ingest_xlsx_returns_three_terms(client):
    b64 = base64.b64encode((INGEST / "data-dictionary.xlsx").read_bytes()).decode()
    resp = post(client, "ingest", {"name": "data-dictionary.xlsx", "base64": b64})
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["terms"]) == 3 and all(t["name"] for t in body["terms"])


def test_ingest_bad_base64_is_422(client):
    assert post(client, "ingest", {"name": "x.csv", "base64": "%%%"}).status_code == 422


@needs_node
def test_propose_with_mock_filters_to_terms_asked(client, mock_llm):
    terms = claims_terms()
    resp = post(client, "propose", {"kind": "terms", "terms": terms})
    assert resp.status_code == 200
    body = resp.get_json()
    asked = {t["name"].lower() for t in terms}
    assert body["model"] == "mock"
    assert body["result"]["terms"] and all(t["name"].lower() in asked for t in body["result"]["terms"])


@needs_node
def test_propose_never_takes_a_raw_prompt(client, mock_llm):
    assert post(client, "propose", {"kind": "prompt", "prompt": "hi"}).status_code == 422


# --- B4, B5, B6: check ----------------------------------------------------------------------

@needs_node
@needs_java
def test_b4_check_straddle_through_owltester(client):
    resp = src(client, "check", fx("straddle-imports-bfo.ttl"), "straddle.ttl")
    assert resp.status_code == 200
    doc = resp.get_json()
    assert doc["verdict"] == {"consistent": True, "coherent": False}
    coh = [f for f in doc["findings"] if f["check"] == "coherence"]
    assert sorted(f["severity"] for f in coh) == ["partition", "within"]
    for f in coh:
        assert f["axioms"] and all("](" not in a and "http" not in a for a in f["axioms"])
        assert not NOTATION.search(f["title"] + f["explanation"])
    part = next(f for f in coh if f["severity"] == "partition")
    assert "continuant DisjointWith occurrent" in part["axioms"]
    assert doc["reasoner"]["name"] == "HermiT"


@needs_node
@needs_java
def test_b5_check_tracker_model(client):
    doc = src(client, "check", fx("job-site-tracker.kindwork.json"), "job-site-tracker.kindwork.json").get_json()
    assert doc["verdict"] == {"consistent": True, "coherent": True}
    assert sorted(f["severity"] for f in doc["findings"]) == ["chain", "chain", "partition"]


@needs_node
def test_b6_forced_timeout_is_undetermined_not_500(client, monkeypatch):
    monkeypatch.setenv("KINDWORK_REASONER_TIMEOUT_MS", "1")
    resp = src(client, "check", fx("straddle-imports-bfo.ttl"), "straddle.ttl")
    assert resp.status_code == 200
    doc = resp.get_json()
    assert doc["verdict"] == {"consistent": None, "coherent": None}
    assert doc["findings"][0]["verdict"] == "undetermined"
    assert all(f["verdict"] != "pass" for f in doc["findings"])


# --- B7, B8: propose failures -------------------------------------------------------------

@needs_node
def test_b7_no_key_is_503_sampling_disabled(client):
    resp = post(client, "propose", {"kind": "terms", "terms": claims_terms()})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "sampling_disabled"


@needs_node
def test_b8_twenty_first_propose_in_an_hour_is_429(app_module, client, mock_llm):
    from abuse_limits import limiter
    app_module.app.config["RATELIMIT_ENABLED"] = True
    limiter.reset()
    try:
        body = {"kind": "terms", "terms": [{"name": "Claim"}]}
        codes = [post(client, "propose", body, **{"X-Forwarded-For": "203.0.113.9"}).status_code
                 for _ in range(21)]
        assert codes[:20] == [200] * 20 and codes[20] == 429
        last = post(client, "propose", body, **{"X-Forwarded-For": "203.0.113.9"})
        assert last.get_json() == {"code": "rate_limited",
                                   "error": "Too many requests just now. Try again in a minute."}
        other = post(client, "propose", body, **{"X-Forwarded-For": "203.0.113.10"})
        assert other.status_code == 200
    finally:
        limiter.reset()
        app_module.app.config["RATELIMIT_ENABLED"] = False


# --- B9 to B12 ------------------------------------------------------------------------------

@needs_node
def test_b9_build_zip_has_six_files_under_slug(client):
    resp = src(client, "build", fx("job-site-tracker.kw"), "job-site-tracker.kw",
               Accept="application/zip")
    assert resp.status_code == 200 and resp.mimetype == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
    assert len(names) == 6 and all(n.startswith("job-site-tracker/") for n in names)


@needs_node
def test_build_errors_are_422_with_five_diagnostics(client):
    resp = src(client, "build", A2_SOURCE, "bad.kw")
    assert resp.status_code == 422
    assert sorted(d["line"] for d in resp.get_json()["errors"]) == [2, 4, 7, 8, 9]


def rpc(client, method, params=None, mid=1):
    return client.post("/kindwork/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method,
                                               "params": params or {}})


@needs_node
def test_b10_mcp_six_tools_and_lint_is_error_line_2(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}).get_json()
    assert init["result"]["capabilities"]["tools"] is not None
    assert client.post("/kindwork/mcp", json={"jsonrpc": "2.0",
                                              "method": "notifications/initialized"}).status_code == 202
    tools = rpc(client, "tools/list").get_json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == [
        "kindwork_build", "kindwork_check", "kindwork_import", "kindwork_ingest",
        "kindwork_lint", "kindwork_propose"]
    res = rpc(client, "tools/call", {"name": "kindwork_lint",
                                     "arguments": {"source": A2_SOURCE, "name": "bad.kw"}}).get_json()
    assert "error" not in res and res["result"]["isError"] is True
    assert json.loads(res["result"]["content"][0]["text"])["errors"][0]["line"] == 2


@needs_node
def test_mcp_propose_without_key_is_tool_error(client):
    res = rpc(client, "tools/call", {"name": "kindwork_propose",
                                     "arguments": {"terms": [{"name": "Claim"}]}}).get_json()
    assert res["result"]["isError"] is True
    assert json.loads(res["result"]["content"][0]["text"])["code"] == "sampling_disabled"


def test_mcp_unknown_method_is_jsonrpc_error(client):
    assert rpc(client, "nope").get_json()["error"]["code"] == -32601


def test_b11_nine_mb_body_is_413(client):
    big = json.dumps({"source": "x" * (9 * 1024 * 1024), "name": "big.kw"})
    assert client.post("/kindwork/v1/build", data=big,
                       content_type="application/json").status_code == 413


def test_b12_module_text_has_no_em_dash(client, monkeypatch):
    paths = [*(ROOT / "kindwork").glob("*.py"), ROOT / "kindwork" / "vocab.ttl",
             ROOT / "templates" / "kindwork.html", *(CORE / "docs").glob("*.md"),
             *(CORE / "src").glob("*.js"), CORE / "bin" / "kindwork-core.mjs"]
    for p in paths:
        assert EM_DASH not in p.read_text(encoding="utf-8"), p
    assert EM_DASH not in client.get("/kindwork").get_data(as_text=True)
    assert EM_DASH not in client.get("/kindwork/workbench").get_data(as_text=True)
    monkeypatch.setenv("KINDWORK_MODE", "full")
    monkeypatch.setenv("KINDWORK_TOKEN", "t")
    assert EM_DASH not in client.get("/kindwork", headers={"Authorization": "Bearer t"}).get_data(as_text=True)


@needs_node
def test_b12_route_replies_have_no_em_dash(client, mock_llm):
    for op, body in [("lint", {"source": fx("job-site-tracker.kw"), "name": "m.kw"}),
                     ("build", {"source": fx("job-site-tracker.kw"), "name": "m.kw"}),
                     ("import", {"source": fx("straddle.ttl"), "name": "straddle.ttl"}),
                     ("build", {"source": A2_SOURCE, "name": "bad.kw"}),
                     ("propose", {"kind": "terms", "terms": claims_terms()})]:
        assert EM_DASH not in post(client, op, body).get_data(as_text=True), op


# --- B13: the measurement log holds counts only ----------------------------------------------

@needs_node
@needs_java
def test_b13_log_holds_counts_and_question_ids_only(app_module, client, mock_llm):
    from kindwork.metrics import KindworkSession
    from models import db
    terms = claims_terms()
    proposed = post(client, "propose", {"kind": "terms", "terms": terms}).get_json()["result"]
    core_manifest = json.loads(fx("job-site-tracker.kindwork.json"))
    # A manifest in the page's shape: the proposed terms, one confirmed as proposed,
    # one confirmed after changing an answer, the rest still proposed.
    mterms = []
    for i, t in enumerate(proposed["terms"]):
        answers = dict(t.get("answers") or {})
        state = "confirmed" if i < 2 else "proposed"
        if i == 1 and answers:
            q = sorted(answers)[0]
            answers[q] = "n" if answers[q] == "y" else "y"
        mterms.append({"id": f"t{i}", "iri": f"https://example.org/kindwork/claims#T{i}",
                       "name": t["name"], "state": state, "answers": answers, "keyword": None})
    manifest = {**core_manifest, "terms": mterms, "relations": [], "conflicts": [], "findings": []}
    assert src(client, "check", json.dumps(manifest), "claims.kindwork.json").status_code == 200
    client.post("/kindwork/v1/event", json={"event": "save-csv"})
    client.post("/kindwork/v1/event", json={"event": "triage"})
    with app_module.app.app_context():
        rows = KindworkSession.query.all()
        row = max(rows, key=lambda r: r.updated_at)
        dump = json.dumps({"counts": row.counts, "state": row.state})
        db.session.delete(row)
        db.session.commit()
    c = json.loads(dump)["counts"]
    assert c["source"] == "paste" and c["terms_in"] == len(terms)
    assert c["terms_proposed"] == len(proposed["terms"])
    assert c["confirmed_unchanged"] == 1 and c["confirmed_changed"] == 1
    assert all(re.fullmatch(r"[a-z0-9]+", q) for q in c["changed_questions"])
    assert c["downloads"] == {"csv": 1} and c["triage_clicked"] is True
    for t in terms:
        assert t["name"].lower() not in dump.lower(), t["name"]


def test_measurement_rows_older_than_twelve_months_are_purged(app_module, client):
    import datetime
    from kindwork.metrics import KindworkSession
    from models import db
    with app_module.app.app_context():
        old = KindworkSession(id="00000000-0000-0000-0000-00000000dead", counts={}, state={},
                              created_at=datetime.datetime.utcnow() - datetime.timedelta(days=400))
        db.session.add(old)
        db.session.commit()
    client.post("/kindwork/v1/event", json={"event": "triage"})  # a new session row
    with app_module.app.app_context():
        assert db.session.get(KindworkSession, "00000000-0000-0000-0000-00000000dead") is None
        for row in KindworkSession.query.all():
            db.session.delete(row)
        db.session.commit()
