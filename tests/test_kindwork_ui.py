"""Browser tests for the Kindwork page as OwlTester serves it (module spec 0.2.0, section 12).

B1 (steps per mode), B2 (the P1 flow), B3 (spreadsheet upload), and the page
halves of B6 (unfinished check), B7 (no model key) and B8 (rate limit). They
drive the real page in headless Chromium against a live server. They skip when
Playwright, its Chromium, Node or Java is missing.
"""

from __future__ import annotations

import csv
import io
import shutil
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "kindwork_core"
INGEST = CORE / "test" / "fixtures" / "ingest"
MOCK = str(INGEST / "mock-proposal.json")

playwright_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("java") is None
    or not (CORE / "node_modules").is_dir(),
    reason="needs Node, Java and kindwork_core/node_modules")


def claims():
    rows = list(csv.reader(io.StringIO((INGEST / "claims-terms.csv").read_text(encoding="utf-8"))))[1:]
    seen, out = set(), []
    for name, desc in rows:
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append((name, desc))
    return out


@pytest.fixture(scope="module")
def server():
    from werkzeug.serving import make_server
    import app as app_module
    app_module.app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    srv = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield app_module, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium not installed for Playwright: {e}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, server, monkeypatch):
    for k in ("KINDWORK_MODE", "KINDWORK_TOKEN", "KINDWORK_LLM_KEY", "ANTHROPIC_API_KEY",
              "SOOL_ANTHROPIC_KEY", "KINDWORK_REASONER_TIMEOUT_MS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KINDWORK_LLM_MOCK", MOCK)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_default_timeout(60000)
    yield pg
    ctx.close()


def open_page(pg, base):
    pg.goto(f"{base}/kindwork")
    pg.wait_for_selector('[data-act="tab"]')


def steps(pg):
    return pg.eval_on_selector_all(
        "nav [data-act=tab], .steps [data-act=tab]",
        "els => els.map(e => e.textContent.trim())") or pg.eval_on_selector_all(
        '[data-act="tab"]', "els => els.filter(e => /^\\d/.test(e.textContent.trim())).map(e => e.textContent.trim())")


def paste_and_propose(pg, terms):
    pg.click('[data-act="tab"][data-tab="describe"] >> nth=0')
    pg.fill("#termlist", "\n".join(f"{n}: {d}" if d else n for n, d in terms))
    pg.check('input[name="impmode"][value="replace"]')
    pg.click('[data-act="proposeterms"]')


def select_term(pg, name):
    pg.click(f'[data-act="sel"]:has-text("{name}")')


def gate_text(pg, name):
    """The status line under a term, after the page settles."""
    pg.wait_for_function("() => !document.querySelector('.gate.busy')")
    select_term(pg, name)
    pg.wait_for_selector(".gate")
    return pg.inner_text(".gate")


def term_row(pg, name):
    return pg.locator(f'[data-act="sel"]:has-text("{name}")').first


# --- B1 -------------------------------------------------------------------------------

def test_b1_four_steps_in_triage_five_in_full(page, server, monkeypatch):
    _, base = server
    open_page(page, base)
    assert len(steps(page)) == 4
    monkeypatch.setenv("KINDWORK_MODE", "full")
    monkeypatch.setenv("KINDWORK_TOKEN", "t")
    page.set_extra_http_headers({"Authorization": "Bearer t"})
    open_page(page, base)
    assert len(steps(page)) == 5


# --- B2 -------------------------------------------------------------------------------

def test_b2_p1_flow(page, server):
    _, base = server
    open_page(page, base)
    terms = claims()
    assert len(terms) == 5
    paste_and_propose(page, terms)
    for name, _ in terms:
        term_row(page, name).wait_for()
        assert "proposed" in term_row(page, name).inner_text().lower(), name

    select_term(page, "Prior authorization")
    with page.expect_response(lambda r: r.url.endswith("/kindwork/v1/check")) as resp:
        page.click('[data-act="confirm"]')
    assert resp.value.status == 200
    assert gate_text(page, "Prior authorization") == \
        "Committed, and the reasoner found nothing against it."
    assert "Committed" in term_row(page, "Prior authorization").inner_text() or \
        "proposed" not in term_row(page, "Prior authorization").inner_text().lower()

    select_term(page, "Claim")
    body = page.inner_text("body").lower()
    assert "held" in body and "happen" in body  # the held-versus-happening card

    page.click('[data-act="tab"][data-tab="build"] >> nth=0')
    table = page.inner_text("table.ttable")
    for name, _ in terms:
        assert name in table, name
    for act, suffix in (("savecsv", ".csv"), ("saveowl", ".ttl")):
        with page.expect_download() as dl:
            page.click(f'[data-act="{act}"]')
        assert dl.value.suggested_filename.endswith(suffix)
        assert Path(dl.value.path()).stat().st_size > 0


# --- B3 -------------------------------------------------------------------------------

def test_b3_spreadsheet_upload_fills_terms(page, server):
    _, base = server
    open_page(page, base)
    page.click('[data-act="tab"][data-tab="describe"] >> nth=0')
    with page.expect_response(lambda r: r.url.endswith("/kindwork/v1/ingest")) as resp:
        page.set_input_files('input[type="file"] >> nth=0', str(INGEST / "data-dictionary.xlsx"))
    assert resp.value.status == 200
    page.wait_for_function("() => document.querySelector('#termlist').value.trim().length > 0")
    lines = [ln for ln in page.input_value("#termlist").splitlines() if ln.strip()]
    assert len(lines) == 3
    assert all(":" in ln for ln in lines), lines  # each with its meaning


# --- B6, B7, B8: the page under failure -----------------------------------------------------

def test_b6_unfinished_check_shows_not_yet_checked(page, server, monkeypatch):
    _, base = server
    monkeypatch.setenv("KINDWORK_REASONER_TIMEOUT_MS", "1")
    open_page(page, base)
    paste_and_propose(page, claims())
    term_row(page, "Prior authorization").wait_for()
    select_term(page, "Prior authorization")
    with page.expect_response(lambda r: r.url.endswith("/kindwork/v1/check")) as resp:
        page.click('[data-act="confirm"]')
    assert resp.value.status == 200
    assert "not yet checked" in gate_text(page, "Prior authorization")


def test_b7_no_key_offers_answer_yourself(page, server, monkeypatch):
    _, base = server
    monkeypatch.delenv("KINDWORK_LLM_MOCK", raising=False)
    open_page(page, base)
    paste_and_propose(page, claims())
    page.wait_for_function(
        "() => { const bar = document.getElementById('kw-keybar');"
        " const text = document.body.innerText.replace(bar ? bar.innerText : '', '');"
        " return text.includes('answer the questions yourself'); }")
    page.wait_for_selector('[data-act="addterms"]')  # "I'll answer myself"
    assert "add your own OpenAI or Anthropic" in page.inner_text("#kw-keybar")


def test_b8_rate_limit_message(page, server):
    app_module, base = server
    from abuse_limits import limiter
    app_module.app.config["RATELIMIT_ENABLED"] = True
    limiter.reset()
    try:
        open_page(page, base)
        for _ in range(20):
            page.request.post(f"{base}/kindwork/v1/propose",
                              data={"kind": "terms", "terms": [{"name": "Claim"}]})
        paste_and_propose(page, claims())
        page.wait_for_function("() => document.body.innerText.includes('Too many requests just now')")
    finally:
        limiter.reset()
        app_module.app.config["RATELIMIT_ENABLED"] = False


# --- the visitor's own key ---------------------------------------------------------------

def test_key_bar_adds_and_removes_the_visitors_key(page, server):
    _, base = server
    open_page(page, base)
    page.wait_for_selector("#kw-keybar")
    assert "add your own OpenAI or Anthropic" in page.inner_text("#kw-keybar")
    page.click("#kw-keybar button:has-text('Add your key')")
    page.select_option("#kw-keybar select", "anthropic")
    page.fill("#kw-keybar input[type=password]", "sk-ant-test-0000000000000000000000")
    page.click("#kw-keybar button:has-text('Save')")
    page.wait_for_selector("#kw-keybar :text('uses your own Anthropic (Claude) key')")
    status = page.request.get(f"{base}/api/settings/openai-key").json()
    assert status == {"has_key": True, "source": "session", "provider": "anthropic"}
    page.click("#kw-keybar button:has-text('Remove key')")
    page.wait_for_selector("#kw-keybar :text('Key removed.')")
    assert page.request.get(f"{base}/api/settings/openai-key").json()["source"] != "session"


def test_key_bar_rejects_a_bad_key(page, server):
    _, base = server
    open_page(page, base)
    page.click("#kw-keybar button:has-text('Add your key')")
    page.select_option("#kw-keybar select", "anthropic")
    page.fill("#kw-keybar input[type=password]", "not-a-key")
    page.click("#kw-keybar button:has-text('Save')")
    page.wait_for_selector("#kw-keybar :text('does not look like an Anthropic API key')")
